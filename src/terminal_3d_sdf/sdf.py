#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
控制台 3D 场景 —— SDF + 水景池 + GPU/CPU 双擎
仅限 Windows 平台
依赖: numpy, pyopencl (可选)
用法: python sdf.py --device=GPU  或  python sdf.py --device=CPU
"""

import sys, os, math, time, threading
import numpy as np
import ctypes
from ctypes import wintypes
import msvcrt
import argparse
import pathlib

# ============================ Windows VT 与 UTF-8 ============================
try:
    _k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    _hout = _k32.GetStdHandle(-11)
    _mode = wintypes.DWORD()
    if _hout != -1 and _k32.GetConsoleMode(_hout, ctypes.byref(_mode)):
        _k32.SetConsoleMode(_hout, _mode.value | 0x0004)
except Exception: pass

try: os.system('chcp 65001 > nul')
except Exception: pass
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass

# ============================ Windows 输入 ============================
_user32 = ctypes.windll.user32
VK_MOVEMENT = {
    'w': 0x57, 'a': 0x41, 's': 0x53, 'd': 0x44, 'r': 0x52, 'f': 0x46,
    'left': 0x25, 'up': 0x26, 'right': 0x27, 'down': 0x28,
}

def get_held_movement_keys():
    return {name for name, vk in VK_MOVEMENT.items() if _user32.GetAsyncKeyState(vk) & 0x8000}

def read_event_keys():
    keys = []
    try:
        while msvcrt.kbhit():
            ch = msvcrt.getwch()
            if ch in ('\x00', '\xe0'):
                try: msvcrt.getwch()
                except Exception: pass
                continue
            keys.append(ch)
    except Exception: pass
    return keys

# ============================ 终端尺寸防抖 ============================
MIN_W, MIN_H = 24, 10
MAX_W, MAX_H = 140, 44

def _raw_term_size():
    try:
        sz = os.get_terminal_size()
        return sz.columns, sz.lines
    except OSError:
        return 80, 24

class SizeWatcher:
    def __init__(self, interval=0.05, debounce=0.25):
        self._interval = interval
        self._debounce = debounce
        self._raw    = _raw_term_size()
        self._stable = self._raw
        self._last_change = time.time()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while not self._stop.is_set():
            sz = _raw_term_size()
            now = time.time()
            with self._lock:
                if sz != self._raw:
                    self._raw = sz
                    self._last_change = now
                elif now - self._last_change >= self._debounce:
                    self._stable = self._raw
            self._stop.wait(self._interval)

    def get(self):
        with self._lock:
            return self._stable, (self._raw == self._stable)
    def stop(self): self._stop.set()

# ============================ 公共参数 ============================
FOV = 0.95
MAX_DIST = 45.0
MOVE_SPEED = 2.5
ROT_SPEED  = 2.0
BLEND_TIME = 0.6

WATER_Y = 0.4
POND_CX, POND_CZ = 0.0, 4.0
POND_RX, POND_RZ = 2.0, 2.0
WALL_W = 0.15
WALL_H = 0.6

SUN = np.array([0.55, 0.78, -0.38], dtype=np.float32); SUN /= np.linalg.norm(SUN)

# ==============================================================================
# ================================== 后端 1: OpenCL GPU =========================
# ==============================================================================
cl_path = pathlib.Path(__file__).resolve().parent / "render.cl"

with open(cl_path, "r", encoding="utf-8") as f:
    cl_kernel_code = f.read()

def init_cl():
    try:
        import pyopencl as cl
        platform = cl.get_platforms()[0]
        device = platform.get_devices()[0]
        print(f"OpenCL 初始化成功，正在编译内核... (设备: {device.name})")
        ctx = cl.Context([device])
        queue = cl.CommandQueue(ctx)
        prg = cl.Program(ctx, cl_kernel_code).build()
        return ctx, queue, prg
    except Exception as e:
        print(f"OpenCL 初始化失败: {e}")
        return None, None, None

# ==============================================================================
# ================================== 后端 2: CPU Numpy =========================
# ==============================================================================
_T_CPU = 0.0
CPU_MAX_STEPS = 64
CPU_SHADOW_STEPS = 12
CPU_USE_AO = True

def get_water_normal_cpu(px, pz, t):
    dx = 0.06 * np.cos(3.0 * px + 2.5 * t) * np.cos(3.0 * pz + 1.8 * t) - \
         0.04 * np.sin(5.0 * px - 1.5 * t) * np.sin(5.0 * pz + 2.0 * t)
    dz = -0.06 * np.sin(3.0 * px + 2.5 * t) * np.sin(3.0 * pz + 1.8 * t) + \
          0.04 * np.cos(5.0 * px - 1.5 * t) * np.cos(5.0 * pz + 2.0 * t)
    nx = -dx * 2.0
    ny = np.ones_like(nx)
    nz = -dz * 2.0
    ln = np.sqrt(nx**2 + ny**2 + nz**2)
    return nx/ln, ny/ln, nz/ln

def sdf_cpu(p):
    n = p.shape[0]
    d   = np.full(n, 1e9)
    mat = np.zeros(n, np.int8)
    
    cy = 0.88 + 0.12 * math.sin(_T_CPU * 1.4)
    dd = np.sqrt((p[:, 0] + 2.5)**2 + (p[:, 1] - cy)**2 + (p[:, 2] + 3.0)**2) - 0.85
    sel = dd < d; d[sel] = dd[sel]; mat[sel] = 1
    dd = np.sqrt((p[:, 0] - 4.0)**2 + (p[:, 1] - 1.0)**2 + (p[:, 2] - 3.0)**2) - 0.72
    sel = dd < d; d[sel] = dd[sel]; mat[sel] = 2
    
    q  = p - np.array([0.0, 1.2, -2.0])
    ca, sa = math.cos(_T_CPU * 0.90), math.sin(_T_CPU * 0.90)
    qx =  q[:, 0] * ca + q[:, 2] * sa; qz = -q[:, 0] * sa + q[:, 2] * ca
    cb, sb = math.cos(_T_CPU * 0.55), math.sin(_T_CPU * 0.55)
    qy2 = q[:, 1] * cb - qz * sb; qz2 = q[:, 1] * sb + qz * cb
    ax, ay, az = np.abs(qx) - 0.55, np.abs(qy2) - 0.55, np.abs(qz2) - 0.55
    outside = np.sqrt(np.maximum(ax, 0.0)**2 + np.maximum(ay, 0.0)**2 + np.maximum(az, 0.0)**2)
    inside  = np.minimum(np.maximum(np.maximum(ax, ay), az), 0.0)
    db = outside + inside - 0.05
    sel = db < d; d[sel] = db[sel]; mat[sel] = 3
    
    q = p - np.array([2.5, 1.2, -3.0])
    ca, sa = math.cos(_T_CPU * 1.1), math.sin(_T_CPU * 1.1)
    qx =  q[:, 0] * ca + q[:, 2] * sa; qz = -q[:, 0] * sa + q[:, 2] * ca
    cb, sb = math.cos(_T_CPU * 0.7), math.sin(_T_CPU * 0.7)
    qy2 = q[:, 1] * cb - qz * sb; qz2 = q[:, 1] * sb + qz * cb
    px, py, pz = np.abs(qx), np.abs(qy2), np.abs(qz2)
    dt = np.maximum(np.maximum(px+py+pz-0.85, px-py-pz-0.85), np.maximum(-px+py-pz-0.85, -px-py+pz-0.85)) * 0.577350269
    sel = dt < d; d[sel] = dt[sel]; mat[sel] = 4
    
    q = p - np.array([4.0, 1.5, -1.0])
    ca, sa = math.cos(_T_CPU * 0.8), math.sin(_T_CPU * 0.8) 
    qx =  q[:, 0] * ca + q[:, 2] * sa; qz = -q[:, 0] * sa + q[:, 2] * ca
    ca2, sa2 = math.cos(math.pi/3), math.sin(math.pi/3)
    qx2 = qx * ca2 - q[:, 1] * sa2; qy2 = qx * sa2 + q[:, 1] * ca2
    d1 = qx2 - 1.0; d2 = -0.5 * qx2 + 0.866025 * qy2 - 1.0; d3 = -0.5 * qx2 - 0.866025 * qy2 - 1.0
    d2d = np.maximum(np.maximum(d1, d2), d3)
    dz = np.abs(qz - 0.0) - 0.04
    dt = np.maximum(d2d, dz)
    sel = dt < d; d[sel] = dt[sel]; mat[sel] = 5
    
    q = p - np.array([-4.0, 1.2, 3.0])
    ca, sa = math.cos(_T_CPU * 0.6), math.sin(_T_CPU * 0.6)
    qx =  q[:, 0] * ca + q[:, 2] * sa; qz = -q[:, 0] * sa + q[:, 2] * ca
    cb, sb = math.cos(_T_CPU * 0.4), math.sin(_T_CPU * 0.4)
    qy2 = q[:, 1] * cb - qz * sb; qz2 = q[:, 1] * sb + qz * cb
    ax, ay, az = np.abs(qx) - 0.55, np.abs(qy2) - 0.55, np.abs(qz2) - 0.55
    outside = np.sqrt(np.maximum(ax, 0.0)**2 + np.maximum(ay, 0.0)**2 + np.maximum(az, 0.0)**2)
    inside  = np.minimum(np.maximum(np.maximum(ax, ay), az), 0.0)
    db = outside + inside - 0.02
    sel = db < d; d[sel] = db[sel]; mat[sel] = 6
    
    wave = 0.04 * np.sin(p[:,0] * 3.0 + _T_CPU * 2.5) * np.cos(p[:,2] * 3.0 + _T_CPU * 1.8) + \
           0.02 * np.cos(p[:,0] * 5.0 - _T_CPU * 1.5) * np.sin(p[:,2] * 5.0 + _T_CPU * 2.0)
    current_water_y = 0.4 + wave
    water_sdf = np.maximum(np.abs(p[:,0] - POND_CX) - (POND_RX - WALL_W/2), np.abs(p[:,2] - POND_CZ) - (POND_RZ - WALL_W/2))
    water_sdf = np.maximum(water_sdf, p[:,1] - current_water_y)
    water_sdf = np.maximum(water_sdf, 0.0 - p[:,1])
    sel = water_sdf < d; d[sel] = water_sdf[sel]; mat[sel] = 7
    
    ball_x = 0.0 + 0.5 * math.sin(_T_CPU * 1.2); ball_z = 4.0 + 0.5 * math.cos(_T_CPU * 1.2)
    ball_wave = 0.04 * np.sin(ball_x * 3.0 + _T_CPU * 2.5) * np.cos(ball_z * 3.0 + _T_CPU * 1.8) + \
                0.02 * np.cos(ball_x * 5.0 - _T_CPU * 1.5) * np.sin(ball_z * 5.0 + _T_CPU * 2.0)
    ball_y = 0.4 + ball_wave - 0.05
    db_ball = np.sqrt((p[:,0] - ball_x)**2 + (p[:,1] - ball_y)**2 + (p[:,2] - ball_z)**2) - 0.35
    sel = db_ball < d; d[sel] = db_ball[sel]; mat[sel] = 9
    
    qw = p - np.array([POND_CX - POND_RX, WALL_H/2, POND_CZ])
    wall_L = np.maximum(np.abs(qw[:,0]) - WALL_W/2, np.abs(qw[:,1]) - WALL_H/2); wall_L = np.maximum(wall_L, np.abs(qw[:,2]) - POND_RZ)
    qw = p - np.array([POND_CX + POND_RX, WALL_H/2, POND_CZ])
    wall_R = np.maximum(np.abs(qw[:,0]) - WALL_W/2, np.abs(qw[:,1]) - WALL_H/2); wall_R = np.maximum(wall_R, np.abs(qw[:,2]) - POND_RZ)
    qw = p - np.array([POND_CX, WALL_H/2, POND_CZ - POND_RZ])
    wall_F = np.maximum(np.abs(qw[:,0]) - POND_RX, np.abs(qw[:,1]) - WALL_H/2); wall_F = np.maximum(wall_F, np.abs(qw[:,2]) - WALL_W/2)
    qw = p - np.array([POND_CX, WALL_H/2, POND_CZ + POND_RZ])
    wall_B = np.maximum(np.abs(qw[:,0]) - POND_RX, np.abs(qw[:,1]) - WALL_H/2); wall_B = np.maximum(wall_B, np.abs(qw[:,2]) - WALL_W/2)
    pool_wall = np.minimum(np.minimum(wall_L, wall_R), np.minimum(wall_F, wall_B))
    sel = pool_wall < d; d[sel] = pool_wall[sel]; mat[sel] = 8
    return d, mat

def march_cpu(ro, rd, tmax=MAX_DIST, steps=None, ignore_mat=0):
    if steps is None: steps = CPU_MAX_STEPS
    n = ro.shape[0]; t = np.zeros(n); alive = np.ones(n, bool); hit = np.zeros(n, bool); mat = np.zeros(n, np.int8)
    for _ in range(steps):
        idx = np.flatnonzero(alive)
        if idx.size == 0: break
        pp = ro[idx] + rd[idx] * t[idx, None]
        d, m = sdf_cpu(pp)
        step_d = np.abs(d)
        if ignore_mat != 0:
            ignore_mask = (m == ignore_mat)
            step_d[ignore_mask] = np.maximum(step_d[ignore_mask], 0.06)
            stop_mask = (d < 1e-3) & (~ignore_mask)
        else: stop_mask = (d < 1e-3)
        t[idx] += step_d
        h = stop_mask
        if h.any():
            hi = idx[h]; hit[hi] = True; mat[hi] = m[h]; alive[hi] = False
        alive[idx[t[idx] > tmax]] = False
    return t, hit, mat

def normal_at_cpu(p):
    e = 0.0012; n = np.empty_like(p)
    for i in range(3):
        dp = p.copy(); dp[:, i] += e
        dm = p.copy(); dm[:, i] -= e
        n[:, i] = sdf_cpu(dp)[0] - sdf_cpu(dm)[0]
    ln = np.linalg.norm(n, axis=1, keepdims=True); ln[ln < 1e-9] = 1.0
    return n / ln

def soft_shadow_cpu(ro, rd, maxt=10.0, steps=None):
    if steps is None: steps = CPU_SHADOW_STEPS
    n = ro.shape[0]; res, t, alive = np.ones(n), np.full(n, 0.02), np.ones(n, bool)
    for _ in range(steps):
        idx = np.flatnonzero(alive)
        if idx.size == 0: break
        pp = ro[idx] + rd[idx] * t[idx, None]
        d, _ = sdf_cpu(pp)
        res[idx] = np.minimum(res[idx], 8.0 * d / np.maximum(t[idx], 1e-4))
        t[idx] += np.clip(np.abs(d), 0.015, 0.30)
        stop = (t[idx] > maxt) | (np.abs(d) < 0.001)
        alive[idx[stop]] = False
        alive[idx[res[idx] < 0.01]] = False
    return np.clip(res, 0.0, 1.0)

def ambient_occlusion_cpu(p, n):
    occ = np.zeros(p.shape[0]); sca = 1.0
    for i in range(1, 6):
        h = 0.01 + 0.16 * i / 5.0
        d, _ = sdf_cpu(p + n * h)
        occ += (h - d) * sca; sca *= 0.88
    return np.clip(1.0 - 2.5 * occ, 0.0, 1.0)

def sky_cpu(d):
    y = np.clip(d[:, 1], -1.0, 1.0)
    a = np.clip(y, 0, 1)[:, None] ** 0.55
    c = np.array([0.72, 0.82, 1.00]) * (1 - a) + np.array([0.14, 0.30, 0.70]) * a
    s = np.clip(d @ SUN, 0, 1) ** 40
    c += s[:, None] * np.array([1.0, 0.88, 0.65]) * 1.6
    c[y < 0] = np.array([0.10, 0.10, 0.13])
    return c

def render_cpu(t, cam_pos, fwd, right, up, cols, rows):
    global _T_CPU
    _T_CPU = t
    
    u = (np.arange(cols) + 0.5) / cols * 2.0 - 1.0
    v = (1.0 - (np.arange(rows) + 0.5) / rows * 2.0) * (rows * 2.0 / cols)
    UU, VV = np.meshgrid(u, v); UU, VV = UU.ravel(), VV.ravel()

    th = math.tan(FOV * 0.5)
    dirs = fwd[None, :] + (UU[:, None] * right[None, :] + VV[:, None] * up[None, :]) * th
    dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
    N = dirs.shape[0]; ro = np.broadcast_to(cam_pos, dirs.shape).copy()
    col = sky_cpu(dirs)
    ground_t = np.full(N, np.inf)
    down = dirs[:, 1] < -1e-8
    if down.any(): ground_t[down] = -ro[down, 1] / dirs[down, 1]
    ground_valid = (ground_t > 1e-4) & (ground_t < MAX_DIST)
    t_obj, hit_obj, mat_obj = march_cpu(ro, dirs)
    use_obj, use_ground = hit_obj & (t_obj < ground_t), (~hit_obj) & ground_valid
    any_hit = use_obj | use_ground
    if any_hit.any():
        idx = np.flatnonzero(any_hit)
        ph = np.zeros((N, 3))
        ph[use_obj] = ro[use_obj] + dirs[use_obj] * t_obj[use_obj][:, None]
        ph[use_ground] = ro[use_ground] + dirs[use_ground] * ground_t[use_ground][:, None]
        nh = np.zeros((N, 3))
        
        if use_obj.any(): nh[use_obj] = normal_at_cpu(ph[use_obj])
        nh[use_ground] = np.array([0.0, 1.0, 0.0])
        
        mh = np.zeros(N, np.int8)
        mh[use_obj] = mat_obj[use_obj]
        
        water_mask_global = (mh == 7)
        if water_mask_global.any():
            px = ph[water_mask_global, 0]
            pz = ph[water_mask_global, 2]
            nx, ny, nz = get_water_normal_cpu(px, pz, _T_CPU)
            nh[water_mask_global] = np.stack([nx, ny, nz], axis=1)

        view_dirs = -dirs[idx]
        flip_mask = np.sum(view_dirs * nh[idx], axis=1) < 0
        nh[idx[flip_mask]] *= -1.0

        t_hit = np.where(use_obj, t_obj, ground_t)
        p_i, n_i, m_i, t_i = ph[idx], nh[idx], mh[idx], t_hit[idx]
        base = np.zeros((idx.size, 3))
        g = (m_i == 0)
        if g.any():
            chk = ((np.floor(p_i[g, 0] * 0.8) + np.floor(p_i[g, 2] * 0.8)).astype(np.int64) & 1).astype(float)[:, None]
            base[g] = np.array([0.58, 0.59, 0.64]) * chk + np.array([0.11, 0.12, 0.16]) * (1.0 - chk)
        base[m_i == 1] = [0.92, 0.30, 0.20]; base[m_i == 2] = [0.20, 0.58, 0.96]
        base[m_i == 3] = [0.62, 0.88, 0.32]; base[m_i == 4] = [0.85, 0.25, 0.85]
        base[m_i == 5] = [0.80, 0.90, 1.00]; base[m_i == 6] = [1.00, 0.70, 0.30]
        base[m_i == 7] = [0.02, 0.10, 0.25]; base[m_i == 8] = [0.90, 0.90, 0.95]
        base[m_i == 9] = [1.00, 0.20, 0.20]
        
        sh = soft_shadow_cpu(p_i + n_i * 0.003, np.broadcast_to(SUN, p_i.shape))
        ao = ambient_occlusion_cpu(p_i, n_i) if CPU_USE_AO else np.ones(idx.size)
        ndl, dif = np.clip(n_i @ SUN, 0.0, 1.0), np.clip(n_i @ SUN, 0.0, 1.0) * sh
        Vv = -dirs[idx]; Hv = Vv + SUN; Hv /= np.linalg.norm(Hv, axis=1, keepdims=True)
        
        spec_pow = np.where(m_i == 7, 80.0, 40.0)
        spc = np.clip(np.sum(n_i * Hv, axis=1), 0.0, 1.0) ** spec_pow * sh
        
        light, amb = [1.00, 0.96, 0.88], (0.28 + 0.72 * ao)[:, None] * np.array([0.34, 0.44, 0.62])
        lit = base * (amb + dif[:, None] * light * 1.20) + spc[:, None] * light * 0.9
        fog = 1.0 - np.exp(-t_i * 0.025)
        fog = np.maximum(fog, np.clip((t_i - MAX_DIST * 0.60) / (MAX_DIST * 0.40), 0.0, 1.0) ** 2)
        lit = lit * (1.0 - fog[:, None]) + sky_cpu(dirs[idx]) * fog[:, None]
        col[idx] = lit
        
        refl_mask = (m_i == 5)
        if refl_mask.any():
            idx_r = np.flatnonzero(refl_mask)
            rd_refl = dirs[idx[refl_mask]] - 2 * np.sum(dirs[idx[refl_mask]] * n_i[refl_mask], axis=1, keepdims=True) * n_i[refl_mask]
            t2, hit2, mat2 = march_cpu(p_i[refl_mask] + rd_refl * 0.02, rd_refl, tmax=35.0, steps=20)
            col_refl = sky_cpu(rd_refl)
            
            if hit2.any():
                ro_h2 = p_i[refl_mask][hit2] + n_i[refl_mask][hit2] * 0.02
                rd_h2 = rd_refl[hit2]
                t_h2 = t2[hit2]
                m_h2 = mat2[hit2]
                
                ph2 = ro_h2 + rd_h2 * t_h2[:, None]
                
                c2 = np.zeros((m_h2.size, 3))
                for k, v in enumerate([ [0.58,0.59,0.64], [0.92,0.3,0.2], [0.2,0.58,0.96], [0.62,0.88,0.32], [0.85,0.25,0.85], [0.8,0.9,1.0], [1.0,0.7,0.3], [0.02,0.10,0.25], [0.9,0.9,0.95], [1.0,0.2,0.2] ]):
                    c2[m_h2 == k] = v
                
                g2 = (m_h2 == 0)
                if g2.any():
                    px2 = np.floor(ph2[g2, 0] * 0.8)
                    pz2 = np.floor(ph2[g2, 2] * 0.8)
                    chk2 = ((px2 + pz2).astype(int) & 1).astype(float)[:, None]
                    c2[g2] = np.array([0.58, 0.59, 0.64]) * chk2 + np.array([0.11, 0.12, 0.16]) * (1.0 - chk2)
                    
                col_refl[hit2] = c2
                
            cos_t = np.abs(np.sum(-dirs[idx[refl_mask]] * n_i[refl_mask], axis=1, keepdims=True))
            fresnel = 0.7 + 0.3 * (1.0 - cos_t)**5
            glass_tint = sky_cpu(dirs[idx[refl_mask]]) * 0.8 + np.array([0.6, 0.85, 1.0]) * 0.2
            col[idx[idx_r]] = col_refl * fresnel + glass_tint * (1.0 - fresnel) + spc[refl_mask][:, None] * 2.5
            
        water_mask_local = (m_i == 7)
        if water_mask_local.any():
            idx_w = np.flatnonzero(water_mask_local)
            rd_w = dirs[idx[water_mask_local]]
            n_w = n_i[water_mask_local]
            p_w = p_i[water_mask_local]
            
            rd_refl = rd_w - 2 * np.sum(rd_w * n_w, axis=1, keepdims=True) * n_w
            t2, hit2, mat2 = march_cpu(p_w + rd_refl * 0.02, rd_refl, tmax=15.0, steps=8)
            col_refl = sky_cpu(rd_refl) * 0.6
            
            if hit2.any():
                c2 = np.zeros((hit2.sum(), 3))
                for k, v in enumerate([ [0.58,0.59,0.64], [0.92,0.3,0.2], [0.2,0.58,0.96], [0.62,0.88,0.32], [0.85,0.25,0.85], [0.8,0.9,1.0], [1.0,0.7,0.3], [0.02,0.10,0.25], [0.9,0.9,0.95], [1.0,0.2,0.2] ]):
                    c2[mat2[hit2] == k] = v
                col_refl[hit2] = c2
            cos_t = np.abs(np.sum(-rd_w * n_w, axis=1, keepdims=True))
            fresnel = 0.05 + 0.95 * (1.0 - cos_t)**5
            col_trans = base[water_mask_local] * 0.6 + sky_cpu(rd_w) * 0.2
            
            water_color = col_refl * fresnel + col_trans * (1.0 - fresnel)
            water_color += spc[water_mask_local][:, None] * 1.5
            
            col[idx[idx_w]] = water_color
            
    col = np.clip(col, 0.0, None)
    col = col / (1.0 + col)
    col = np.clip(col, 0.0, 1.0) ** (1.0 / 2.2)
    rgb = (col * 255.0 + 0.5).astype(np.int32)
    lines = []
    for r in range(rows):
        row = rgb[r * cols:(r + 1) * cols]
        idxs = np.concatenate(([0], np.flatnonzero(np.any(row[1:] != row[:-1], axis=1)) + 1, [cols]))
        segs = []
        for i in range(len(idxs) - 1):
            s, e = int(idxs[i]), int(idxs[i + 1])
            segs.append('\x1b[38;2;%d;%d;%dm' % (int(row[s, 0]), int(row[s, 1]), int(row[s, 2])))
            segs.append('█' * (e - s))
        segs.append('\x1b[K')
        lines.append('\x1b[%d;1H' % (r + 1))
        lines.append(''.join(segs))
    return ''.join(lines)

# ==============================================================================
# ==================================== 主程序 ===================================
# ==============================================================================
def main():
    global W, H
    
    parser = argparse.ArgumentParser(description="Console 3D SDF Renderer")
    parser.add_argument('--device', type=str, default='GPU', choices=['GPU', 'CPU'], help="选择渲染设备: GPU (OpenCL) 或 CPU (Numpy)")
    args = parser.parse_args()

    use_gpu = False
    ctx, queue, prg = None, None, None
    
    if args.device == 'GPU':
        ctx, queue, prg = init_cl()
        if ctx is not None:
            use_gpu = True
        else:
            print("警告: GPU 初始化失败，自动回退到 CPU。")
    else:
        print("已根据命令行参数强制使用 CPU 渲染。")

    watcher = SizeWatcher()
    out = sys.stdout
    out.write('\x1b[?1049h\x1b[?25l\x1b[2J\x1b[H\x1b[?7l')
    out.flush()

    anim_t = 0.0
    last = time.time()
    paused = False
    frame_count, fps_window_t0, fps_display = 0, time.time(), 0.0
    cam_pos, cam_yaw, cam_pitch = np.array([0.0, 3.2, 7.0]), math.pi, -0.25
    autopilot, blend = True, 1.0

    W, H = 80, 30
    max_nbytes = MAX_W * MAX_H * 3
    rgb_host_max = np.empty((max_nbytes,), dtype=np.uint8)
    rgb_dev = None
    if use_gpu:
        import pyopencl as cl
        rgb_dev = cl.Buffer(ctx, cl.mem_flags.WRITE_ONLY, max_nbytes)

    try:
        while True:
            frame_start = time.time()
            dt = min(frame_start - last, 0.1)
            last = frame_start

            events = read_event_keys()
            for ch in events:
                lc = ch.lower()
                if lc in ('q', '\x1b'): raise KeyboardInterrupt
                elif lc == ' ': paused = not paused
                elif lc == 't':
                    autopilot = not autopilot
                    if autopilot: blend = 0.0

            held = get_held_movement_keys()
            if held and not paused: autopilot = False
            if autopilot and held: blend = 0.0

            stable_size, is_stable = watcher.get()
            if not is_stable:
                time.sleep(0.02)
                continue

            cols, rows = stable_size
            new_W, new_H = min(cols - 2, MAX_W), min(rows - 3, MAX_H)
            
            if new_W != W or new_H != H:
                W, H = new_W, new_H
                out.write('\x1b[2J\x1b[H')
                last = time.time()

            frame_count += 1
            if frame_start - fps_window_t0 >= 0.5:
                fps_display = frame_count / (frame_start - fps_window_t0)
                frame_count, fps_window_t0 = 0, frame_start

            cy_h, sy_h = math.cos(cam_yaw), math.sin(cam_yaw)
            fh, rt = np.array([sy_h, 0.0, cy_h]), np.array([cy_h, 0.0, -sy_h])
            move = np.zeros(3)
            if 'w' in held: move += fh
            if 's' in held: move -= fh
            if 'd' in held: move += rt
            if 'a' in held: move -= rt
            if 'r' in held: move[1] += 1.0
            if 'f' in held: move[1] -= 1.0
            if np.any(move): cam_pos += (move / np.linalg.norm(move)) * MOVE_SPEED * dt

            if 'left'  in held: cam_yaw   -= ROT_SPEED * dt
            if 'right' in held: cam_yaw   += ROT_SPEED * dt
            if 'up'    in held: cam_pitch += ROT_SPEED * dt
            if 'down'  in held: cam_pitch -= ROT_SPEED * dt
            cam_pitch = max(-1.45, min(1.45, cam_pitch))
            if cam_pos[1] < 0.2: cam_pos[1] = 0.2

            if not paused: anim_t += dt

            if autopilot and not paused:
                ang = anim_t * 0.35
                auto_cam = np.array([math.sin(ang) * 8.0, 3.2 + 0.5 * math.sin(anim_t * 0.45), math.cos(ang) * 8.0])
                auto_fwd = np.array([0.0, 1.0, 0.0]) - auto_cam
                auto_fwd /= np.linalg.norm(auto_fwd)
                if blend < 1.0: blend = min(1.0, blend + dt / BLEND_TIME)
                if blend >= 1.0:
                    cam_pos, fwd = auto_cam.copy(), auto_fwd.copy()
                else:
                    tb = blend * blend * (3.0 - 2.0 * blend)
                    m_fwd = np.array([math.sin(cam_yaw)*math.cos(cam_pitch), math.sin(cam_pitch), math.cos(cam_yaw)*math.cos(cam_pitch)])
                    cam_pos = cam_pos * (1.0 - tb) + auto_cam * tb
                    fwd = m_fwd * (1.0 - tb) + auto_fwd * tb
                    fwd /= np.linalg.norm(fwd)
                cam_pitch = math.asin(float(np.clip(fwd[1], -1.0, 1.0)))
                cam_yaw   = math.atan2(float(fwd[0]), float(fwd[2]))
            else:
                cp, sp = math.cos(cam_pitch), math.sin(cam_pitch)
                fwd = np.array([math.sin(cam_yaw)*cp, sp, math.cos(cam_yaw)*cp])

            right = np.cross(np.array([0.0, 1.0, 0.0]), fwd)
            right /= np.linalg.norm(right)
            up = np.cross(fwd, right)

            if use_gpu:
                import pyopencl as cl
                cam_pos_f = np.array([cam_pos[0], cam_pos[1], cam_pos[2], 0.0], dtype=np.float32)
                fwd_f = np.array([fwd[0], fwd[1], fwd[2], 0.0], dtype=np.float32)
                right_f = np.array([right[0], right[1], right[2], 0.0], dtype=np.float32)
                up_f = np.array([up[0], up[1], up[2], 0.0], dtype=np.float32)

                prg.render_kernel(queue, (W, H), None, rgb_dev, cam_pos_f, fwd_f, right_f, up_f,
                                  np.float32(anim_t), np.int32(W), np.int32(H), np.int32(48), np.int32(1), np.float32(FOV))
                
                target_view = rgb_host_max[:W*H*3]
                cl.enqueue_copy(queue, target_view, rgb_dev).wait()

                parts = []
                idx = 0
                for r in range(H):
                    parts.append('\x1b[%d;1H' % (r + 1))
                    lc = None
                    for c in range(W):
                        R, G, B = int(target_view[idx]), int(target_view[idx+1]), int(target_view[idx+2])
                        idx += 3
                        if (R, G, B) != lc:
                            parts.append(f'\x1b[38;2;{R};{G};{B}m')
                            lc = (R, G, B)
                        parts.append('█')
                    parts.append('\x1b[K')
                frame_str = ''.join(parts)
                engine = "GPU"
            else:
                frame_str = render_cpu(anim_t, cam_pos, fwd, right, up, W, H)
                engine = "CPU"

            mode = 'AUTO' if autopilot else 'FREE'
            state = 'PAUSE' if paused else 'PLAY '
            status = ' %5.1f FPS [%s] %s %s  %dx%d  WASD/RF Move  Arrows Look  T Auto  Sp Pause  Q Quit' % (
                fps_display, engine, mode, state, W, H)
            if len(status) > cols - 3: status = status[:cols - 3]

            out.write('\x1b[0m' + frame_str + '\x1b[0m')
            out.write('\x1b[%d;1H\x1b[K' % (H + 1) + status)
            out.write('\x1b[%d;1H\x1b[J' % (H + 2))
            out.flush()

            frame_end = time.time()
            elapsed = frame_end - frame_start
            if elapsed < (1.0 / 60):
                time.sleep((1.0 / 60) - elapsed)

    except KeyboardInterrupt: pass
    finally:
        watcher.stop()
        if rgb_dev is not None:
            try: rgb_dev.release()
            except Exception: pass
        out.write('\x1b[0m\x1b[?25h\x1b[?7h\x1b[?1049l\n')
        out.flush()
