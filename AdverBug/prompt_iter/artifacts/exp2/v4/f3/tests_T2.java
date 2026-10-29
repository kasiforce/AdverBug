package tools.jackson.databind.deser.jdk;

import org.junit.Test;
import static org.junit.Assert.*;

import tools.jackson.databind.ObjectMapper;
import tools.jackson.core.JacksonException;

public class DeserializeFromObjectTests {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Test
    public void testDeserializeFromObject_basicMessage() throws Exception {
        String json = "{\"message\":\"boom\"}";
        Throwable t = MAPPER.readValue(json, Throwable.class);
        assertNotNull(t);
        assertEquals("boom", t.getMessage());
    }

    @Test
    public void testDeserializeFromObject_withSuppressed() throws Exception {
        String json = "{\"message\":\"root\",\"suppressed\":[{\"message\":\"s1\"},{\"message\":\"s2\"}]}";
        Throwable t = MAPPER.readValue(json, Throwable.class);
        assertEquals("root", t.getMessage());

        Throwable[] supp = t.getSuppressed();
        assertNotNull(supp);
        assertEquals(2, supp.length);
        assertEquals("s1", supp[0].getMessage());
        assertEquals("s2", supp[1].getMessage());
    }

    @Test
    public void testDeserializeFromObject_suppressedNull() throws Exception {
        String json = "{\"message\":\"root\",\"suppressed\":null}";
        Throwable t = MAPPER.readValue(json, Throwable.class);
        assertEquals("root", t.getMessage());

        Throwable[] supp = t.getSuppressed();
        assertNotNull(supp);
        assertEquals(0, supp.length);
    }

    @Test
    public void testDeserializeFromObject_unknownPropertyThrows() throws Exception {
        String json = "{\"foo\":123}";
        try {
            MAPPER.readValue(json, Throwable.class);
            fail("Expected JacksonException due to unknown property");
        } catch (JacksonException e) {
            // expected
        }
    }
}