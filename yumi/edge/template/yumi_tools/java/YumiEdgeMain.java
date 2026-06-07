import java.util.concurrent.CountDownLatch;

/**
 * Standalone entry: run this class from your IDE, or {@code mvn exec:java} with this as mainClass.
 * Delete this class when you integrate {@link YumiSetup#initYumi()} into your application's main.
 */
public class YumiEdgeMain {

    public static void main(String[] args) throws InterruptedException {
        YumiSetup.initYumi();
        System.err.println("Yumi edge running. Press Ctrl+C to exit.");
        new CountDownLatch(1).await();
    }
}
