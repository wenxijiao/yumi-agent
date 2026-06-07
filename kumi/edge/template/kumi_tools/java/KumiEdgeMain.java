import java.util.concurrent.CountDownLatch;

/**
 * Standalone entry: run this class from your IDE, or {@code mvn exec:java} with this as mainClass.
 * Delete this class when you integrate {@link KumiSetup#initKumi()} into your application's main.
 */
public class KumiEdgeMain {

    public static void main(String[] args) throws InterruptedException {
        KumiSetup.initKumi();
        System.err.println("Kumi edge running. Press Ctrl+C to exit.");
        new CountDownLatch(1).await();
    }
}
