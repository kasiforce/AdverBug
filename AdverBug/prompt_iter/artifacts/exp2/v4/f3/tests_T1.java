package tools.jackson.databind.deser.jdk;

import org.junit.Test;
import static org.junit.Assert.*;

import tools.jackson.databind.ObjectMapper;

public class DeserializeFromObjectTests {

    private final ObjectMapper MAPPER = new ObjectMapper();

    @Test
    public void testBasicMessageDeserialization() throws Exception {
        String json = "{\"message\":\"boom\"}";
        Throwable t = MAPPER.readValue(json, Throwable.class);
        assertNotNull(t);
        assertEquals("boom", t.getMessage());
    }

    @Test
    public void testSuppressedDeserialization() throws Exception {
        String json = "{\"message\":\"main\",\"suppressed\":[{\"message\":\"a\"},{\"message\":\"b\"}]}";
        Throwable t = MAPPER.readValue(json, Throwable.class);
        assertNotNull(t);
        assertEquals("main", t.getMessage());

        Throwable[] suppressed = t.getSuppressed();
        assertNotNull(suppressed);
        assertEquals(2, suppressed.length);
        assertEquals("a", suppressed[0].getMessage());
        assertEquals("b", suppressed[1].getMessage());
    }

    @Test
    public void testSuppressedNullHandled() throws Exception {
        String json = "{\"message\":\"hasNoSuppressed\",\"suppressed\":null}";
        Throwable t = MAPPER.readValue(json, Throwable.class);
        assertNotNull(t);
        assertEquals("hasNoSuppressed", t.getMessage());

        // Depending on implementation, suppressed may be empty
        Throwable[] suppressed = t.getSuppressed();
        assertNotNull(suppressed);
        assertEquals(0, suppressed.length);
    }

    @Test(expected = Exception.class)
    public void testUnknownPropertyThrows() throws Exception {
        String json = "{\"unknownProp\":123}";
        // Unknown properties should typically cause an error for Throwable deserialization
        MAPPER.readValue(json, Throwable.class);
    }

    @Test
    public void testRepeatedDeserializationIsConsistent() throws Exception {
        String json = "{\"message\":\"dup\"}";
        Throwable t1 = MAPPER.readValue(json, Throwable.class);
        Throwable t2 = MAPPER.readValue(json, Throwable.class);
        assertNotNull(t1);
        assertNotNull(t2);
        assertEquals(t1.getMessage(), t2.getMessage());
    }
}