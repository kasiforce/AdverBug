package tools.jackson.databind.deser.jdk;

import org.junit.Test;
import static org.junit.Assert.*;

import tools.jackson.databind.ObjectMapper;

public class DeserializeFromObjectTests {

    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    public void testDeserializeMessageOnly() throws Exception {
        String json = "{\"message\":\"foo\"}";
        Throwable t = mapper.readValue(json, Throwable.class);
        assertNotNull("Deserialized Throwable should not be null", t);
        assertEquals("foo", t.getMessage());
        assertEquals(0, t.getSuppressed().length);
    }

    @Test
    public void testDeserializeSuppressed() throws Exception {
        String json = "{\"suppressed\":[{\"message\":\"secret\"}]}";
        Throwable t = mapper.readValue(json, Throwable.class);
        assertNotNull("Deserialized Throwable should not be null", t);
        assertNull("Outer throwable message should be null when not provided", t.getMessage());
        Throwable[] suppressed = t.getSuppressed();
        assertNotNull("Suppressed array should not be null", suppressed);
        assertEquals("There should be one suppressed throwable", 1, suppressed.length);
        assertEquals("secret", suppressed[0].getMessage());
    }

    @Test
    public void testDeserializeEmptyObject() throws Exception {
        String json = "{}";
        Throwable t = mapper.readValue(json, Throwable.class);
        assertNotNull("Deserialized Throwable should not be null", t);
        // Without message, default constructor should be used; message may be null
        assertNull("Message should be null for empty object", t.getMessage());
    }

    @Test
    public void testLocalizedMessageIgnored() throws Exception {
        String json = "{\"localizedMessage\":\"ignored\"}";
        Throwable t = mapper.readValue(json, Throwable.class);
        assertNotNull("Deserialized Throwable should not be null", t);
        // localizedMessage should be ignored; message remains unaffected
        assertNull("Message should remain null when only localizedMessage is provided", t.getMessage());
    }

    @Test
    public void testStackTraceSetEmpty() throws Exception {
        String json = "{\"stackTrace\":[]}";
        Throwable t = mapper.readValue(json, Throwable.class);
        assertNotNull("Deserialized Throwable should not be null", t);
        assertEquals("Stack trace should be empty after deserialization", 0, t.getStackTrace().length);
    }
}