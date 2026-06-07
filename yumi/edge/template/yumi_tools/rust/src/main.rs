mod yumi_setup;

#[tokio::main]
async fn main() {
    yumi_setup::init_yumi();
    eprintln!("Yumi edge running. Press Ctrl+C to stop.");
    let _ = tokio::signal::ctrl_c().await;
}
