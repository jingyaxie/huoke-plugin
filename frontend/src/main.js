import { createApp } from "vue";
import ElementPlus from "element-plus";
import "element-plus/dist/index.css";
import App from "./App.vue";
import router from "./router";
import { initRuntimeEnv } from "./api/localService";
import "./styles.css";

function showBootError(message) {
  const root = document.getElementById("app");
  if (!root) return;
  root.innerHTML = `
    <div style="max-width:720px;margin:48px auto;padding:24px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;line-height:1.6;color:#222;">
      <h1 style="color:#c0392b;font-size:22px;">前端加载失败</h1>
      <pre style="white-space:pre-wrap;background:#f6f6f6;padding:16px;border-radius:8px;font-size:13px;">${message}</pre>
      <p style="color:#666;">请打开开发者工具 Network 面板，检查 <code>/assets/*.js</code> 是否 404；桌面版请重新安装或执行打包脚本。</p>
    </div>
  `;
}

try {
  createApp(App).use(router).use(ElementPlus).mount("#app");
  void initRuntimeEnv().catch(() => {});
} catch (error) {
  const message = error instanceof Error ? error.stack || error.message : String(error);
  showBootError(message);
  console.error(error);
}

