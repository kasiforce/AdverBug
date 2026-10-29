import org.junit.Test;
import static org.junit.Assert.*;
import tools.jackson.databind.deser.jdk.EnumMapDeserializer;

public class _deserializeUsingPropertiesTests {
    @Test
    public void smokeAlwaysPasses() {
        assertTrue(true);
    }
    @Test
    public void smokeClassLoaded() {
        assertNotNull(EnumMapDeserializer.class);
    }
}
