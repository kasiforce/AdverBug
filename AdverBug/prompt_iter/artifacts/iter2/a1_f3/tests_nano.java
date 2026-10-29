package tools.jackson.databind.deser.jdk;

import org.junit.Before;
import org.junit.Test;

import java.io.IOException;

import tools.jackson.databind.MapperFeature;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.Assert.*;

/**
 * Tests for Throwable deserialization via deserializeFromObject path.
 * These tests exercise basic behavior of deserializing a Throwable from JSON,
 * including handling of the "message" field, "suppressed" array, and unknown properties.
 */
public class DeserializeFromObjectTests {

    private ObjectMapper mapper;

    @Before
    public void setup() {
        mapper = new ObjectMapper();
    }

    @Test
    public void testDeserialize_MessageProperty() throws IOException {
        Throwable t = mapper.readValue("{\"message\":\"boom\"}", Throwable.class);
        assertNotNull("Deserialized throwable should not be null", t);
        assertEquals("boom", t.getMessage());
    }

    @Test
    public void testDeserialize_SuppressedArrayEmpty() throws IOException {
        Throwable t = mapper.readValue("{\"suppressed\":[]}", Throwable.class);
        assertNotNull("Deserialized throwable should not be null", t);
        assertNotNull("Suppressed array should be initialized", t.getSuppressed());
        assertEquals("Suppressed should be empty", 0, t.getSuppressed().length);
    }

    @Test
    public void testDeserialize_LocalizedMessageIgnored() throws IOException {
        Throwable t = mapper.readValue("{\"localizedMessage\":\"ignored\"}", Throwable.class);
        // localizedMessage should be ignored; message remains null
        assertNull("Message should be null when only localizedMessage is provided", t.getMessage());
    }

    @Test(expected = JacksonException.class)
    public void testDeserialize_UnknownPropertyThrowsWhenConfigured() throws IOException {
        // Enable strict unknown property handling to trigger an exception for unknown fields
        ObjectMapper mapper = JsonMapper.builder()
                .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                .build();

        // This should fail because "foo" is not a known property for Throwable
        mapper.readValue("{\"foo\":1}", Throwable.class);
    }
}