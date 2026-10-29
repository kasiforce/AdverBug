package tools.jackson.databind.deser.jdk;

import org.junit.Test;
import static org.junit.Assert.*;

import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.DeserializationFeature;

import java.io.IOException;

public class DeserializeFromObjectTests {

    @Test
    public void testBasicMessageDeserialization() throws IOException {
        String json = "{\"message\":\"hello world\"}";
        ObjectMapper mapper = new ObjectMapper();
        Throwable t = mapper.readValue(json, Throwable.class);

        assertNotNull(t);
        assertEquals("hello world", t.getMessage());
        assertEquals(0, t.getSuppressed().length);
    }

    @Test
    public void testSuppressedDeserialization() throws IOException {
        String json = "{\"message\":\"outer\",\"suppressed\":[{\"message\":\"inner\"}]}";
        ObjectMapper mapper = new ObjectMapper();
        Throwable t = mapper.readValue(json, Throwable.class);

        assertNotNull(t);
        assertEquals("outer", t.getMessage());

        Throwable[] suppressed = t.getSuppressed();
        assertEquals(1, suppressed.length);
        assertEquals("inner", suppressed[0].getMessage());
    }

    @Test
    public void testUnknownPropertyIgnored() throws IOException {
        String json = "{\"message\":\"ok\",\"unknownProp\":\"value\"}";
        ObjectMapper mapper = JsonMapper.builder()
                .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false)
                .build();

        Throwable t = mapper.readValue(json, Throwable.class);
        assertNotNull(t);
        assertEquals("ok", t.getMessage());
    }

    @Test
    public void testLocalizedMessageIgnored() throws IOException {
        String json = "{\"message\":\"outer\",\"localizedMessage\":\"ignored\"}";
        ObjectMapper mapper = new ObjectMapper();

        Throwable t = mapper.readValue(json, Throwable.class);
        assertNotNull(t);
        assertEquals("outer", t.getMessage());
        // By default, getLocalizedMessage() should equal getMessage() unless overridden
        assertEquals(t.getMessage(), t.getLocalizedMessage());
    }
}