use std::env;
use std::fs::File;
use std::io::{BufRead, BufReader};

/// Load a simple `KEY=value` `.env` file. Does not override existing env vars.
pub fn load_env_file(path: &str) {
    let Ok(file) = File::open(path) else {
        return;
    };
    for line in BufReader::new(file).lines().map_while(Result::ok) {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let Some((key, mut value)) = line.split_once('=') else {
            continue;
        };
        let key = key.trim();
        value = value.trim();
        if value.len() >= 2 {
            let b = value.as_bytes();
            if (b[0] == b'"' && b[value.len() - 1] == b'"')
                || (b[0] == b'\'' && b[value.len() - 1] == b'\'')
            {
                value = &value[1..value.len() - 1];
            }
        }
        if env::var(key).unwrap_or_default().is_empty() {
            env::set_var(key, value);
        }
    }
}
