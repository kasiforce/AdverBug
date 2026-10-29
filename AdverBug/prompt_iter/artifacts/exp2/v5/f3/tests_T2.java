package tools.jackson.databind.deser.jdk;

import static org.junit.Assert.*;

import org.junit.Test;

import tools.jackson.databind.ObjectMapper;

public class DeserializeFromObjectTests {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Test
    public void testMessageDeserializesFromObject() throws Exception {
        String json = "{\"message\":\"hello\"}";
        Throwable t = MAPPER.readValue(json, Throwable.class);
        assertNotNull(t);
        assertEquals("hello", t.getMessage());
    }

    @Test
    public void testMessageCaseInsensitiveDeserializes() throws Exception {
        String json = "{\"MESSage\":\"HiThere\"}";
        Throwable t = MAPPER.readValue(json, Throwable.class);
        assertNotNull(t);
        assertEquals("HiThere", t.getMessage());
    }

    @Test
    public void testNoMessageResultsInNullMessage() throws Exception {
        String json = "{}";
        Throwable t = MAPPER.readValue(json, Throwable.class);
        assertNotNull(t);
        assertNull(t.getMessage());
    }
}