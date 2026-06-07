mod kumi_setup;

#[tokio::main]
async fn main() {
    kumi_setup::init_kumi();
    eprintln!("Kumi edge running. Press Ctrl+C to stop.");
    let _ = tokio::signal::ctrl_c().await;
}
