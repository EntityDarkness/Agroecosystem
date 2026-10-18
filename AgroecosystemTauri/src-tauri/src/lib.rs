use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{fs, io::Write, net::TcpListener, path::Path, process::{Child, Command, Stdio}, sync::Mutex, time::{Duration, SystemTime, UNIX_EPOCH}};
use tauri::Manager;
mod model_store;

struct Service {
    child: Mutex<Option<Child>>,
    client: reqwest::Client,
    url: String,
    token: String,
    startup_error: Option<String>,
}

const BUNDLED_MODELS: &[(&str, &[u8])] = &[
    ("module1_model_BOD.pkl", include_bytes!("../../../models/module1_model_BOD.pkl")),
    ("module1_model_COD.pkl", include_bytes!("../../../models/module1_model_COD.pkl")),
    ("module1_model_Ammonium.pkl", include_bytes!("../../../models/module1_model_Ammonium.pkl")),
    ("module1_model_Phosphates.pkl", include_bytes!("../../../models/module1_model_Phosphates.pkl")),
    ("module1_model_Nitrates.pkl", include_bytes!("../../../models/module1_model_Nitrates.pkl")),
    ("module1_model_Nitrites.pkl", include_bytes!("../../../models/module1_model_Nitrites.pkl")),
    ("module1_model_Fats.pkl", include_bytes!("../../../models/module1_model_Fats.pkl")),
    ("module1_model_Sulfates.pkl", include_bytes!("../../../models/module1_model_Sulfates.pkl")),
    ("module2_dosing_config.pkl", include_bytes!("../../../python_service/data/models/module2_dosing_config.pkl")),
    ("module3_sediments.pkl", include_bytes!("../../../python_service/data/models/module3_sediments.pkl")),
];

fn sync_bundled_models(data: &Path) -> std::io::Result<()> {
    let mut hasher = Sha256::new();
    for (name, bytes) in BUNDLED_MODELS { hasher.update(name.as_bytes()); hasher.update(bytes); }
    let version = format!("{:x}", hasher.finalize());
    model_store::sync_models(data, BUNDLED_MODELS, &version)
}

fn hidden(command: &mut Command) -> &mut Command {
    #[cfg(windows)] {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    command
}

impl Service {
    fn stop(&self) {
        if let Ok(mut slot) = self.child.lock() {
            if let Some(mut child) = slot.take() {
                #[cfg(windows)] {
                    let _ = hidden(Command::new("taskkill").args(["/PID", &child.id().to_string(), "/T", "/F"]))
                        .stdout(Stdio::null()).stderr(Stdio::null()).status();
                }
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}

impl Drop for Service {
    fn drop(&mut self) { self.stop(); }
}

#[tauri::command]
fn export_report(app: tauri::AppHandle, contents: String, format: String) -> Result<String, String> {
    if !matches!(format.as_str(), "csv" | "json") || contents.len() > 4 * 1024 * 1024 {
        return Err("Некорректный формат или слишком большой отчёт".into());
    }
    let directory = app.path().download_dir().map_err(|e| e.to_string())?.join("Агроэкосистема");
    fs::create_dir_all(&directory).map_err(|e| e.to_string())?;
    let stamp = SystemTime::now().duration_since(UNIX_EPOCH).map_err(|e| e.to_string())?.as_millis();
    let path = directory.join(format!("agro-report-{stamp}-{}.{}", &uuid::Uuid::new_v4().to_string()[..8], format));
    let mut file = fs::OpenOptions::new().write(true).create_new(true).open(&path).map_err(|e| e.to_string())?;
    file.write_all(contents.as_bytes()).map_err(|e| e.to_string())?;
    Ok(path.to_string_lossy().into_owned())
}

#[tauri::command]
async fn service_request(state: tauri::State<'_, Service>, path: String, body: Option<Value>) -> Result<Value, String> {
    if let Some(error) = &state.startup_error { return Err(error.clone()); }
    let allowed = matches!(path.as_str(), "/health" | "/meta" | "/dataset" | "/observations" | "/predict/indicators" | "/predict/dosing" | "/predict/sediments" | "/retrain")
        || (path.starts_with("/observations/") && path[14..].chars().all(|c| c.is_ascii_digit() || c == '-'));
    if !allowed { return Err("Неизвестная операция".into()); }
    let url = format!("{}{}", state.url, path);
    let request = match body {
        Some(value) => state.client.post(url).json(&value),
        None => state.client.get(url),
    };
    let response = request.bearer_auth(&state.token).send().await.map_err(|e| format!("Сервис ещё запускается или недоступен: {e}"))?;
    let status = response.status();
    let value: Value = response.json().await.map_err(|e| format!("Некорректный ответ сервиса: {e}"))?;
    if !status.is_success() {
        return Err(value.get("detail").map(|v| v.as_str().map(str::to_owned).unwrap_or_else(|| v.to_string())).unwrap_or_else(|| status.to_string()));
    }
    Ok(value)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            if let Some(window) = app.get_webview_window("main") { let _ = window.show(); let _ = window.set_focus(); }
        }))
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            let data = app.path().app_data_dir()?.join("wtp-data");
            fs::create_dir_all(&data)?;
            sync_bundled_models(&data)?;
            let listener = TcpListener::bind("127.0.0.1:0")?;
            let port = listener.local_addr()?.port();
            drop(listener);
            let token = uuid::Uuid::new_v4().to_string();
            let executable = std::env::current_exe()?;
            let mut binary = executable.parent().ok_or("Нет каталога приложения")?.join(if cfg!(windows) { "python_service.exe" } else { "python_service" });
            if cfg!(debug_assertions) {
                binary = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("binaries").join(if cfg!(windows) { "python_service-x86_64-pc-windows-msvc.exe" } else { "python_service-x86_64-unknown-linux-gnu" });
            }
            let log = fs::OpenOptions::new().create(true).truncate(true).write(true).open(data.join("service.log"))?;
            let mut command = Command::new(binary);
            command.args(["--host", "127.0.0.1", "--port", &port.to_string(), "--data-dir"])
                .arg(&data).env("WTP_API_TOKEN", &token)
                .stdin(Stdio::null()).stderr(Stdio::from(log.try_clone()?)).stdout(Stdio::from(log));
            let (child, startup_error) = match hidden(&mut command).spawn() {
                Ok(child) => (Some(child), None),
                Err(error) => (None, Some(format!("Не удалось запустить ML-сервис: {error}"))),
            };
            app.manage(Service {
                child: Mutex::new(child),
                client: reqwest::Client::builder().no_proxy().timeout(Duration::from_secs(300)).build()?,
                url: format!("http://127.0.0.1:{port}"), token, startup_error,
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![service_request, export_report])
        .build(tauri::generate_context!())
        .expect("Не удалось запустить Агроэкосистему");
    app.run(|handle, event| {
        if matches!(event, tauri::RunEvent::Exit) { handle.state::<Service>().stop(); }
    });
}
