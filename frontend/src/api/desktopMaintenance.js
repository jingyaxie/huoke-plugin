import http from "./http";

export async function fetchDesktopHealth() {
  const { data } = await http.get("/health");
  return data;
}

export async function repairDesktopRuntime() {
  const { data } = await http.post("/desktop/repair");
  return data;
}

export async function downloadDesktopDiagnostics() {
  const response = await http.get("/desktop/diagnostics", {
    responseType: "blob",
  });
  const disposition = response.headers["content-disposition"] || "";
  const match = disposition.match(/filename="([^"]+)"/);
  const filename = match?.[1] || "huoke-diagnostics.zip";
  return { blob: response.data, filename };
}
