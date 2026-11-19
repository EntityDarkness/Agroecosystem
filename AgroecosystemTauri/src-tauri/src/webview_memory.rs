#![cfg(target_os = "windows")]

use tauri::WebviewWindow;
use webview2_com::Microsoft::Web::WebView2::Win32::{
    ICoreWebView2_19, COREWEBVIEW2_MEMORY_USAGE_TARGET_LEVEL_LOW,
    COREWEBVIEW2_MEMORY_USAGE_TARGET_LEVEL_NORMAL,
};
use windows::core::Interface;

/// Устанавливает уровень памяти WebView2 для указанного окна.
pub fn set_memory_level(window: &WebviewWindow, low: bool) -> Result<(), String> {
    window
        .with_webview(move |platform_webview| {
            let controller = platform_webview.controller();
            let core = unsafe { controller.CoreWebView2() }
                .map_err(|e| format!("CoreWebView2: {e}"))?;

            let core19 = core
                .cast::<ICoreWebView2_19>()
                .map_err(|e| format!("ICoreWebView2_19 (старый Runtime?): {e}"))?;

            let level = if low {
                COREWEBVIEW2_MEMORY_USAGE_TARGET_LEVEL_LOW
            } else {
                COREWEBVIEW2_MEMORY_USAGE_TARGET_LEVEL_NORMAL
            };

            unsafe {
                core19
                    .SetMemoryUsageTargetLevel(level)
                    .map_err(|e| format!("SetMemoryUsageTargetLevel: {e}"))?;
            }
            Ok(())
        })
        .map_err(|e| format!("with_webview: {e}"))??;
    Ok(())
}

/// Синхронизирует уровень памяти с текущим состоянием окна.
pub fn sync_memory_level(window: &WebviewWindow) {
    let visible = window.is_visible().unwrap_or(true);
    let minimized = window.is_minimized().unwrap_or(false);
    let focused = window.is_focused().unwrap_or(false);

    // Экономим память, если окно скрыто, свёрнуто или не в фокусе
    let low = !visible || minimized || !focused;
    let _ = set_memory_level(window, low);
}