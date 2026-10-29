package tools.jackson.databind.deser.jdk;

import tools.jackson.databind.ObjectMapper;
import java.util.Properties;

import org.junit.Test;

import static org.junit.Assert.assertEquals;

public class _deserializeUsingPropertiesTests {
    private final ObjectMapper MAPPER = new ObjectMapper();

    @Test
    public void testDeserializePropertiesFromSimpleJson() throws Exception {
        String json = "{\"a\":\"1\",\"b\":\"two\"}";
        Properties props = MAPPER.readValue(json, Properties.class);
        assertEquals("1", props.getProperty("a"));
        assertEquals("two", props.getProperty("b"));
        assertEquals(2, props.size());
    }
}