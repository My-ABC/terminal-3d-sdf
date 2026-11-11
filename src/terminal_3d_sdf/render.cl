typedef struct { float dist; int mat; } SDFResult;
typedef struct { float3 rgb; } Color;
constant float3 SUN = (float3)(0.55f, 0.78f, -0.38f);

inline float wave_height(float x, float z, float t) {
    return 0.04f * sin(x * 3.0f + t * 2.5f) * cos(z * 3.0f + t * 1.8f) + 
           0.02f * cos(x * 5.0f - t * 1.5f) * sin(z * 5.0f + t * 2.0f);
}

inline float3 get_water_normal(float3 p, float _T) {
    float dx = 0.06f * cos(3.0f * p.x + 2.5f * _T) * cos(3.0f * p.z + 1.8f * _T) - 
               0.04f * sin(5.0f * p.x - 1.5f * _T) * sin(5.0f * p.z + 2.0f * _T);
    float dz = -0.06f * sin(3.0f * p.x + 2.5f * _T) * sin(3.0f * p.z + 1.8f * _T) + 
                0.04f * cos(5.0f * p.x - 1.5f * _T) * cos(5.0f * p.z + 2.0f * _T);
    return normalize((float3)(-dx * 2.0f, 1.0f, -dz * 2.0f));
}

inline SDFResult get_sdf(float3 p, float _T) {
    float d = 1e9f; int mat = 0;
    
    float cy = 0.88f + 0.12f * sin(_T * 1.4f);
    float dd = length(p - (float3)(-2.5f, cy, -3.0f)) - 0.85f;
    if (dd < d) { d = dd; mat = 1; }
    
    dd = length(p - (float3)(4.0f, 1.0f, 3.0f)) - 0.72f;
    if (dd < d) { d = dd; mat = 2; }
    
    float3 q = p - (float3)(0.0f, 1.2f, -2.0f);
    float ca = cos(_T * 0.9f), sa = sin(_T * 0.9f);
    float qx = q.x * ca + q.z * sa; float qz = -q.x * sa + q.z * ca;
    float cb = cos(_T * 0.55f), sb = sin(_T * 0.55f);
    float qy2 = q.y * cb - qz * sb; float qz2 = q.y * sb + qz * cb;
    float3 a = fabs((float3)(qx, qy2, qz2)) - (float3)(0.55f, 0.55f, 0.55f);
    float outside = length(max(a, (float3)(0.0f))); float inside = min(max(max(a.x, a.y), a.z), 0.0f);
    float db = outside + inside - 0.05f; if (db < d) { d = db; mat = 3; }
    
    q = p - (float3)(2.5f, 1.2f, -3.0f);
    ca = cos(_T * 1.1f); sa = sin(_T * 1.1f); qx = q.x * ca + q.z * sa; qz = -q.x * sa + q.z * ca;
    cb = cos(_T * 0.7f); sb = sin(_T * 0.7f); qy2 = q.y * cb - qz * sb; qz2 = q.y * sb + qz * cb;
    float3 pp = fabs((float3)(qx, qy2, qz2));
    float dt = max(max(pp.x+pp.y+pp.z-0.85f, pp.x-pp.y-pp.z-0.85f), max(-pp.x+pp.y-pp.z-0.85f, -pp.x-pp.y+pp.z-0.85f)) * 0.577350269f;
    if (dt < d) { d = dt; mat = 4; }
    
    q = p - (float3)(4.0f, 1.5f, -1.0f);
    ca = cos(_T * 0.8f); sa = sin(_T * 0.8f); qx = q.x * ca + q.z * sa; qz = -q.x * sa + q.z * ca;
    float ca2 = 0.5f, sa2 = 0.866025f;
    float qx2 = qx * ca2 - q.y * sa2; qy2 = qx * sa2 + q.y * ca2; qz2 = qz;
    float d1 = qx2 - 1.0f; float d2 = -0.5f * qx2 + 0.866025f * qy2 - 1.0f; float d3 = -0.5f * qx2 - 0.866025f * qy2 - 1.0f;
    float d2d = max(max(d1, d2), d3); float dz = fabs(qz2) - 0.04f; dt = max(d2d, dz);
    if (dt < d) { d = dt; mat = 5; }
    
    q = p - (float3)(-4.0f, 1.2f, 3.0f);
    ca = cos(_T * 0.6f); sa = sin(_T * 0.6f); qx = q.x * ca + q.z * sa; qz = -q.x * sa + q.z * ca;
    cb = cos(_T * 0.4f); sb = sin(_T * 0.4f); qy2 = q.y * cb - qz * sb; qz2 = q.y * sb + qz * cb;
    a = fabs((float3)(qx, qy2, qz2)) - (float3)(0.55f, 0.55f, 0.55f);
    outside = length(max(a, (float3)(0.0f))); inside = min(max(max(a.x, a.y), a.z), 0.0f);
    db = outside + inside - 0.02f; if (db < d) { d = db; mat = 6; }
    
    float wave = wave_height(p.x, p.z, _T); float current_water_y = 0.4f + wave;
    float water_sdf = max(fabs(p.x - 0.0f) - 1.9f, fabs(p.z - 4.0f) - 1.9f);
    water_sdf = max(water_sdf, p.y - current_water_y); water_sdf = max(water_sdf, 0.0f - p.y);
    if (water_sdf < d) { d = water_sdf; mat = 7; }
    
    float ball_x = 0.0f + 0.5f * sin(_T * 1.2f);
    float ball_z = 4.0f + 0.5f * cos(_T * 1.2f);
    float ball_y = 0.4f + wave_height(ball_x, ball_z, _T) - 0.05f;
    db = length(p - (float3)(ball_x, ball_y, ball_z)) - 0.35f;
    if (db < d) { d = db; mat = 9; }
    
    float3 qw = p - (float3)(-2.0f, 0.3f, 4.0f); float wall_L = max(fabs(qw.x) - 0.075f, fabs(qw.y) - 0.3f); wall_L = max(wall_L, fabs(qw.z) - 2.0f);
    qw = p - (float3)(2.0f, 0.3f, 4.0f); float wall_R = max(fabs(qw.x) - 0.075f, fabs(qw.y) - 0.3f); wall_R = max(wall_R, fabs(qw.z) - 2.0f);
    qw = p - (float3)(0.0f, 0.3f, 2.0f); float wall_F = max(fabs(qw.x) - 2.0f, fabs(qw.y) - 0.3f); wall_F = max(wall_F, fabs(qw.z) - 0.075f);
    qw = p - (float3)(0.0f, 0.3f, 6.0f); float wall_B = max(fabs(qw.x) - 2.0f, fabs(qw.y) - 0.3f); wall_B = max(wall_B, fabs(qw.z) - 0.075f);
    float pool_wall = min(min(wall_L, wall_R), min(wall_F, wall_B));
    if (pool_wall < d) { d = pool_wall; mat = 8; }
    SDFResult res = {d, mat}; return res;
}

inline float3 get_normal(float3 p, float _T) {
    float e = 0.0012f;
    float3 dp = (float3)(get_sdf(p + (float3)(e,0,0), _T).dist - get_sdf(p - (float3)(e,0,0), _T).dist, get_sdf(p + (float3)(0,e,0), _T).dist - get_sdf(p - (float3)(0,e,0), _T).dist, get_sdf(p + (float3)(0,0,e), _T).dist - get_sdf(p - (float3)(0,0,e), _T).dist);
    return normalize(dp);
}
inline float3 sky_color(float3 d) {
    float y = clamp(d.y, -1.0f, 1.0f); float a = pow(clamp(y, 0.0f, 1.0f), 0.55f);
    float3 c = (float3)(0.72f, 0.82f, 1.00f) * (1.0f - a) + (float3)(0.14f, 0.30f, 0.70f) * a;
    float s = pow(clamp(dot(d, SUN), 0.0f, 1.0f), 40.0f);
    c += (float3)(s * 1.6f, s * 1.408f, s * 1.04f); if (y < 0.0f) c = (float3)(0.10f, 0.10f, 0.13f);
    return c;
}
inline Color material_color(int mat) {
    Color c;
    if (mat == 0) c.rgb = (float3)(0.58f, 0.59f, 0.64f); else if (mat == 1) c.rgb = (float3)(0.92f, 0.30f, 0.20f);
    else if (mat == 2) c.rgb = (float3)(0.20f, 0.58f, 0.96f); else if (mat == 3) c.rgb = (float3)(0.62f, 0.88f, 0.32f);
    else if (mat == 4) c.rgb = (float3)(0.85f, 0.25f, 0.85f); else if (mat == 5) c.rgb = (float3)(0.80f, 0.90f, 1.00f);
    else if (mat == 6) c.rgb = (float3)(1.00f, 0.70f, 0.30f); else if (mat == 7) c.rgb = (float3)(0.02f, 0.10f, 0.25f);
    else if (mat == 8) c.rgb = (float3)(0.90f, 0.90f, 0.95f); else if (mat == 9) c.rgb = (float3)(1.00f, 0.20f, 0.20f);
    else c.rgb = (float3)(0.0f, 0.0f, 0.0f); return c;
}
inline float trace_shadow(float3 ro, float3 rd, float _T, int max_steps) {
    float res = 1.0f; float t = 0.02f;
    for (int i = 0; i < max_steps; i++) {
        float3 p = ro + rd * t; float d = get_sdf(p, _T).dist; res = min(res, 8.0f * d / max(t, 1e-4f)); t += clamp(fabs(d), 0.015f, 0.30f);
        if (t > 10.0f || fabs(d) < 0.001f) break; if (res < 0.01f) break;
    } return clamp(res, 0.0f, 1.0f);
}
inline float calc_ao(float3 p, float3 n, float _T) {
    float occ = 0.0f, sca = 1.0f;
    for (int i = 1; i <= 5; i++) { float h = 0.01f + 0.16f * (float)i / 5.0f; float d = get_sdf(p + n * h, _T).dist; occ += (h - d) * sca; sca *= 0.88f; }
    return clamp(1.0f - 2.5f * occ, 0.0f, 1.0f);
}
inline float3 clamp_color(float3 c) { return clamp(c / (1.0f + c), 0.0f, 1.0f); }

__kernel void render_kernel(__global uchar *out_rgb, float4 cam_pos4, float4 fwd4, float4 right4, float4 up4, float _T, int width, int height, int max_steps, int use_ao, float fov) {
    float3 cam_pos = cam_pos4.xyz; float3 fwd = fwd4.xyz; float3 right = right4.xyz; float3 up = up4.xyz;
    int x = get_global_id(0); int y = get_global_id(1); if (x >= width || y >= height) return;
    
    float u = (x + 0.5f) / (float)width * 2.0f - 1.0f;
    float v = (1.0f - (y + 0.5f) / (float)height * 2.0f) * ((float)height * 2.0f / (float)width);
    float th = tan(fov * 0.5f);
    
    float3 dirs = normalize(fwd + (u * right + v * up) * th); 
    float3 col = sky_color(dirs);
    float t_ground = 1e9f; if (dirs.y < -1e-8f) { float gt = -cam_pos.y / dirs.y; if (gt > 1e-4f && gt < 45.0f) t_ground = gt; }
    float t = 0.0f; int mat = -1;
    for (int i = 0; i < max_steps; i++) { float3 p = cam_pos + dirs * t; SDFResult sdf = get_sdf(p, _T); t += fabs(sdf.dist); if (sdf.dist < 1e-3f) { mat = sdf.mat; break; } if (t > 45.0f) break; }
    bool use_obj = (mat != -1) && (t < t_ground); bool use_gnd = (mat == -1) && (t_ground < 1e9f);
    if (use_obj || use_gnd) {
        float t_hit = use_obj ? t : t_ground; float3 p_i = cam_pos + dirs * t_hit; 
        
        float3 n_i;
        if (mat == 7) n_i = get_water_normal(p_i, _T);
        else n_i = use_obj ? get_normal(p_i, _T) : (float3)(0.0f, 1.0f, 0.0f);
        
        if (dot(-dirs, n_i) < 0.0f) n_i = -n_i;
        int m_i = use_obj ? mat : 0; float3 base = material_color(m_i).rgb;
        if (m_i == 0) { int chk = ((int)floor(p_i.x * 0.8f) + (int)floor(p_i.z * 0.8f)) & 1; base = chk ? (float3)(0.58f, 0.59f, 0.64f) : (float3)(0.11f, 0.12f, 0.16f); }
        
        float sh = trace_shadow(p_i + n_i * 0.003f, SUN, _T, 12); 
        float ao = use_ao ? calc_ao(p_i, n_i, _T) : 1.0f; float ndl = clamp(dot(n_i, SUN), 0.0f, 1.0f); float dif = ndl * sh;
        float3 Vv = -dirs; float3 Hv = normalize(Vv + SUN); 
        
        float spec_pow = (m_i == 7) ? 80.0f : 40.0f;
        float spc = pow(clamp(dot(n_i, Hv), 0.0f, 1.0f), spec_pow) * sh;
        
        float3 light = (float3)(1.00f, 0.96f, 0.88f); float3 amb = (0.28f + 0.72f * ao) * (float3)(0.34f, 0.44f, 0.62f); float3 lit = base * (amb + dif * light * 1.2f) + spc * light * 0.9f;
        float fog = 1.0f - exp(-t_hit * 0.025f); float fade = clamp((t_hit - 45.0f * 0.6f) / (45.0f * 0.4f), 0.0f, 1.0f); fog = max(fog, fade * fade);
        lit = lit * (1.0f - fog) + sky_color(dirs) * fog; col = lit;
        
        if (m_i == 5 || m_i == 7) {
            float3 rd_refl = dirs - 2.0f * dot(dirs, n_i) * n_i; float3 col_refl = sky_color(rd_refl);
            if (m_i == 5) {
                float t2 = 0.0f; int mat2 = -1;
                float3 p2;
                for (int i = 0; i < 16; i++) { 
                    p2 = p_i + n_i * 0.02f + rd_refl * t2; 
                    SDFResult sdf2 = get_sdf(p2, _T); 
                    t2 += fabs(sdf2.dist); 
                    if (sdf2.dist < 1e-3f) { mat2 = sdf2.mat; break; } 
                    if (t2 > 35.0f) break; 
                }
                if (mat2 != -1) {
                    if (mat2 == 0) {
                        int chk2 = ((int)floor(p2.x * 0.8f) + (int)floor(p2.z * 0.8f)) & 1;
                        col_refl = chk2 ? (float3)(0.58f, 0.59f, 0.64f) : (float3)(0.11f, 0.12f, 0.16f);
                    } else {
                        col_refl = material_color(mat2).rgb;
                    }
                }
            } else {
                col_refl *= 0.6f;
            }
            
            float cos_theta = fabs(dot(-dirs, n_i)); 
            float fresnel = (m_i == 5) ? (0.7f + 0.3f * pow(1.0f - cos_theta, 5.0f)) : (0.05f + 0.95f * pow(1.0f - cos_theta, 5.0f));
            
            float3 tint = (m_i == 5) ? (sky_color(dirs) * 0.8f + (float3)(0.6f, 0.85f, 1.0f) * 0.2f) : (base * 0.6f + sky_color(dirs) * 0.2f);
            
            if (m_i == 7) {
                col = col_refl * fresnel + tint * (1.0f - fresnel) + spc * 1.5f;
            } else {
                col = col_refl * fresnel + tint * (1.0f - fresnel) + spc * 2.0f;
            }
        }
    }
    
    col = clamp_color(col); col = pow(col, (float3)(1.0f / 2.2f)); int idx = (y * width + x) * 3;
    out_rgb[idx + 0] = (uchar)(col.x * 255.0f); out_rgb[idx + 1] = (uchar)(col.y * 255.0f); out_rgb[idx + 2] = (uchar)(col.z * 255.0f);
}