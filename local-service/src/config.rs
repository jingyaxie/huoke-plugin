pub const DEFAULT_PORT: u16 = 18766;

pub struct AppConfig {
    pub host: String,
    pub port: u16,
    pub data_dir: std::path::PathBuf,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            host: "127.0.0.1".into(),
            port: DEFAULT_PORT,
            data_dir: default_data_dir(),
        }
    }
}

fn default_data_dir() -> std::path::PathBuf {
    std::env::var("HUOKE_DATA_DIR")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|_| {
            std::env::current_dir()
                .unwrap_or_else(|_| std::path::PathBuf::from("."))
                .join("storage")
                .join("local-service")
        })
}

impl AppConfig {
    pub fn from_env() -> Self {
        let port = std::env::var("HUOKE_LOCAL_PORT")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(DEFAULT_PORT);
        let data_dir = std::env::var("HUOKE_DATA_DIR")
            .map(std::path::PathBuf::from)
            .unwrap_or_else(|_| default_data_dir());
        Self {
            host: "127.0.0.1".into(),
            port,
            data_dir,
        }
    }

    pub fn addr(&self) -> String {
        format!("{}:{}", self.host, self.port)
    }

    pub fn db_path(&self) -> std::path::PathBuf {
        self.data_dir.join("huoke_local.db")
    }
}
