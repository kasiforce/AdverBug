package tools.jackson.databind.deser.jdk;

import static org.junit.Assert.*;

import org.junit.Test;

import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.exc.UnrecognizedPropertyException;

public class DeserializeFromObjectTests {

    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    public void testBasicMessageDeserialization() throws Exception {
        String json = "{\"message\":\"boom\"}";
        Throwable t = mapper.readValue(json, Throwable.class);
        assertNotNull(t);
        assertEquals("boom", t.getMessage());
    }

    @Test
    public void testSuppressedDeserialization() throws Exception {
        String json = "{\"message\":\"top\",\"suppressed\":[{\"message\":\"a\"},{\"message\":\"b\"}]}";
        Throwable t = mapper.readValue(json, Throwable.class);
        assertNotNull(t);
        assertEquals("top", t.getMessage());

        Throwable[] suppressed = t.getSuppressed();
        assertNotNull(suppressed);
        assertEquals(2, suppressed.length);
        assertEquals("a", suppressed[0].getMessage());
        assertEquals("b", suppressed[1].getMessage());
    }

    @Test
    public void testLocalizedMessageIgnored() throws Exception {
        String json = "{\"localizedMessage\":\"ignoredValue\"}";
        Throwable t = mapper.readValue(json, Throwable.class);
        // localizedMessage should be ignored per implementation
        assertNull(t.getMessage());
    }

    @Test
    public void testUnknownPropertyFailsWhenConfigured() throws Exception {
        ObjectMapper mapperFail = JsonMapper.builder()
                .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                .build();
        String json = "{\"unknownProp\":1}";
        try {
            mapperFail.readValue(json, Throwable.class);
            fail("Expected UnrecognizedPropertyException due to unknown property");
        } catch (UnrecognizedPropertyException ex) {
            // expected
        }
    }
}