pub const STARTUP_SPLASH_HTML: &str = r#"<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>启动中</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow:hidden}
body{
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  color:#eef3ff;
  background:#060818;
  display:flex;align-items:center;justify-content:center;
}
.bg{position:fixed;inset:0;overflow:hidden;z-index:0}
.orb{position:absolute;border-radius:50%;filter:blur(72px);opacity:.55;animation:drift 14s ease-in-out infinite alternate}
.orb-a{width:420px;height:420px;background:#3b82f6;top:-80px;left:-60px}
.orb-b{width:360px;height:360px;background:#8b5cf6;bottom:-60px;right:-40px;animation-delay:-4s}
.orb-c{width:280px;height:280px;background:#06b6d4;top:40%;left:55%;animation-delay:-7s}
.grid{
  position:absolute;inset:0;
  background-image:
    linear-gradient(rgba(255,255,255,.04) 1px,transparent 1px),
    linear-gradient(90deg,rgba(255,255,255,.04) 1px,transparent 1px);
  background-size:48px 48px;
  mask-image:radial-gradient(circle at center,black 20%,transparent 75%);
  animation:gridPulse 6s ease-in-out infinite;
}
@keyframes drift{
  0%{transform:translate(0,0) scale(1)}
  100%{transform:translate(36px,-28px) scale(1.08)}
}
@keyframes gridPulse{0%,100%{opacity:.35}50%{opacity:.65}}
.shell{position:relative;z-index:1;width:min(92vw,520px);text-align:center;padding:32px 24px}
.logo-wrap{
  width:112px;height:112px;margin:0 auto 28px;position:relative;
  display:grid;place-items:center;
}
.logo-ring,.logo-ring-2{
  position:absolute;inset:0;border-radius:28px;
  border:2px solid transparent;
}
.logo-ring{
  background:linear-gradient(#0b1028,#0b1028) padding-box,
    linear-gradient(135deg,#60a5fa,#a78bfa,#22d3ee) border-box;
  animation:spin 8s linear infinite;
}
.logo-ring-2{
  inset:10px;border-radius:20px;
  border:1px solid rgba(255,255,255,.12);
  animation:spin 12s linear infinite reverse;
}
.logo-core{
  width:64px;height:64px;border-radius:18px;
  background:linear-gradient(145deg,rgba(96,165,250,.25),rgba(167,139,250,.18));
  box-shadow:0 0 40px rgba(96,165,250,.35), inset 0 0 24px rgba(255,255,255,.08);
  display:grid;place-items:center;font-size:28px;font-weight:800;
  background-clip:padding-box;
  animation:corePulse 2.4s ease-in-out infinite;
}
.logo-core span{
  background:linear-gradient(135deg,#dbeafe,#c4b5fd,#67e8f9);
  -webkit-background-clip:text;background-clip:text;color:transparent;
}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes corePulse{
  0%,100%{transform:scale(1);box-shadow:0 0 40px rgba(96,165,250,.35), inset 0 0 24px rgba(255,255,255,.08)}
  50%{transform:scale(1.04);box-shadow:0 0 56px rgba(139,92,246,.45), inset 0 0 28px rgba(255,255,255,.12)}
}
.title{
  font-size:clamp(28px,5vw,36px);font-weight:700;letter-spacing:.04em;
  background:linear-gradient(90deg,#f8fafc,#dbeafe 45%,#ddd6fe 80%,#a5f3fc);
  -webkit-background-clip:text;background-clip:text;color:transparent;
  animation:titleGlow 3s ease-in-out infinite;
}
.subtitle{margin-top:10px;font-size:15px;color:rgba(226,232,240,.72);letter-spacing:.08em}
.steps{margin-top:28px;display:flex;justify-content:center;gap:10px}
.dot{width:8px;height:8px;border-radius:50%;background:rgba(148,163,184,.35);animation:dotBounce 1.4s ease-in-out infinite}
.dot:nth-child(2){animation-delay:.16s}
.dot:nth-child(3){animation-delay:.32s}
@keyframes dotBounce{
  0%,80%,100%{transform:translateY(0);background:rgba(148,163,184,.35)}
  40%{transform:translateY(-8px);background:#93c5fd}
}
.progress{margin:26px auto 0;width:min(360px,86vw);height:6px;border-radius:999px;background:rgba(255,255,255,.08);overflow:hidden;position:relative}
.progress::before{
  content:"";position:absolute;inset:0;
  background:linear-gradient(90deg,transparent,rgba(255,255,255,.08),transparent);
  animation:shimmer 2s linear infinite;
}
.bar{
  height:100%;width:42%;border-radius:inherit;
  background:linear-gradient(90deg,#3b82f6,#8b5cf6,#22d3ee);
  box-shadow:0 0 18px rgba(59,130,246,.55);
  animation:barSlide 2.2s ease-in-out infinite;
}
.hint{margin-top:16px;font-size:13px;color:rgba(148,163,184,.85)}
@keyframes barSlide{
  0%{transform:translateX(-120%)}
  100%{transform:translateX(320%)}
}
@keyframes shimmer{0%{transform:translateX(-100%)}100%{transform:translateX(100%)}}
@keyframes titleGlow{0%,100%{filter:drop-shadow(0 0 8px rgba(96,165,250,.15))}50%{filter:drop-shadow(0 0 16px rgba(167,139,250,.35))}}
.particles{position:fixed;inset:0;pointer-events:none;z-index:0}
.particle{
  position:absolute;width:4px;height:4px;border-radius:50%;
  background:rgba(147,197,253,.8);
  animation:rise linear infinite;
}
.particle:nth-child(1){left:12%;bottom:-10px;animation-duration:7s;animation-delay:.2s}
.particle:nth-child(2){left:28%;bottom:-10px;animation-duration:9s;animation-delay:1.1s;width:3px;height:3px}
.particle:nth-child(3){left:44%;bottom:-10px;animation-duration:8s;animation-delay:.6s}
.particle:nth-child(4){left:61%;bottom:-10px;animation-duration:10s;animation-delay:1.8s;width:5px;height:5px}
.particle:nth-child(5){left:78%;bottom:-10px;animation-duration:7.5s;animation-delay:.9s}
.particle:nth-child(6){left:90%;bottom:-10px;animation-duration:8.5s;animation-delay:2.2s;width:3px;height:3px}
@keyframes rise{
  0%{transform:translateY(0) scale(.6);opacity:0}
  10%{opacity:.9}
  100%{transform:translateY(-110vh) scale(1);opacity:0}
}
</style>
</head>
<body>
<div class="bg">
  <div class="orb orb-a"></div>
  <div class="orb orb-b"></div>
  <div class="orb orb-c"></div>
  <div class="grid"></div>
</div>
<div class="particles">
  <span class="particle"></span><span class="particle"></span><span class="particle"></span>
  <span class="particle"></span><span class="particle"></span><span class="particle"></span>
</div>
<div class="shell">
  <div class="logo-wrap">
    <div class="logo-ring"></div>
    <div class="logo-ring-2"></div>
    <div class="logo-core"><span>盈</span></div>
  </div>
  <h1 class="title">盈小蚁</h1>
  <p class="subtitle">正在唤醒本地引擎</p>
  <div class="steps"><span class="dot"></span><span class="dot"></span><span class="dot"></span></div>
  <div class="progress"><div class="bar"></div></div>
  <p class="hint">加载界面 · 启动服务 · 连接插件</p>
</div>
</body>
</html>"#;
