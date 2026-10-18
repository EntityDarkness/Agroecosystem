//! Обновляет только поставку моделей. Измерения и локальное дообучение сохраняются.
use std::{fs, path::Path, time::{SystemTime, UNIX_EPOCH}};

pub fn sync_models(data: &Path, bundled: &[(&str, &[u8])], revision: &str) -> std::io::Result<()> {
    let marker = data.join(".bundled-models.sha256");
    if fs::read_to_string(&marker).ok().as_deref() == Some(revision) { return Ok(()); }
    let models = data.join("models");
    if models.exists() {
        let stamp = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_nanos();
        let backup = data.join(format!("models-backup-{stamp}"));
        fs::create_dir(&backup)?;
        for (name, _) in bundled {
            let existing = models.join(name);
            if existing.exists() { fs::copy(existing, backup.join(name))?; }
        }
    }
    fs::create_dir_all(&models)?;
    for (name, bytes) in bundled {
        let next = models.join(format!("{name}.next"));
        fs::write(&next, bytes)?;
        fs::rename(next, models.join(name))?;
    }
    fs::write(marker, revision)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    struct TestDirectory { root: std::path::PathBuf, path: std::path::PathBuf }
    impl TestDirectory {
        fn new() -> Self {
            let root=std::env::temp_dir().canonicalize().unwrap();
            let stamp=SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
            let path=root.join(format!("agro-model-store-test-{stamp}"));
            fs::create_dir(&path).unwrap();
            Self { root,path }
        }
    }
    impl Drop for TestDirectory {
        fn drop(&mut self) {
            if let Ok(target)=self.path.canonicalize() {
                if target.parent()==Some(self.root.as_path()) && target.file_name().unwrap().to_string_lossy().starts_with("agro-model-store-test-") {
                    let _=fs::remove_dir_all(target);
                }
            }
        }
    }
    #[test]
    fn upgrade_preserves_history_and_local_training_until_release_changes() {
        let temp=TestDirectory::new(); let data=&temp.path;
        let bundle: &[(&str,&[u8])]=&[("model.pkl",b"release model"),("config.pkl",b"config")];
        fs::write(data.join("panel_monthly.csv"),"user measurements").unwrap();
        sync_models(data,bundle,"release-1").unwrap();
        let model=data.join("models/model.pkl");
        assert_eq!(fs::read(&model).unwrap(),b"release model");
        fs::write(&model,b"user retrained model").unwrap();
        sync_models(data,bundle,"release-1").unwrap();
        assert_eq!(fs::read(&model).unwrap(),b"user retrained model");
        sync_models(data,bundle,"release-2").unwrap();
        assert_eq!(fs::read(&model).unwrap(),b"release model");
        assert_eq!(fs::read_to_string(data.join("panel_monthly.csv")).unwrap(),"user measurements");
        let backup=fs::read_dir(data).unwrap().map(|e|e.unwrap().path()).find(|p|p.file_name().unwrap().to_string_lossy().starts_with("models-backup-")).unwrap();
        assert_eq!(fs::read(backup.join("model.pkl")).unwrap(),b"user retrained model");
    }
}
