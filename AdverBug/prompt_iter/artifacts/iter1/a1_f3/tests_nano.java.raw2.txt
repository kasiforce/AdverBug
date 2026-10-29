package tools.jackson.databind.deser.jdk;

import org.junit.Test;
import static org.junit.Assert.*;

import tools.jackson.databind.ObjectMapper;

public class DeserializeFromObjectTests {
    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Test
    public void testDeserializeMessageOnly() throws Exception {
        Throwable t = MAPPER.readValue("{\"message\":\"boom\"}", Throwable.class);
        assertNotNull(t);
        assertEquals("boom", t.getMessage());
        assertEquals(0, t.getSuppressed().length);
        assertNull(t.getCause());
    }

    @Test
    public void testDeserializeWithSuppressed() throws Exception {
        Throwable t = MAPPER.readValue("{\"message\":\"outer\",\"suppressed\":[{\"message\":\"inner\"}]}",
            Throwable.class);
        assertNotNull(t);
        assertEquals("outer", t.getMessage());
        Throwable[] supp = t.getSuppressed();
        assertNotNull(supp);
        assertEquals(1, supp.length);
        assertEquals("inner", supp[0].getMessage());
    }

    @Test
    public void testUnknownPropertyIgnored() throws Exception {
        Throwable t = MAPPER.readValue("{\"foo\":1,\"message\":\"OK\"}", Throwable.class);
        assertNotNull(t);
        assertEquals("OK", t.getMessage());
    }

    @Test
    public void testLocalizedMessageIgnored() throws Exception {
        Throwable t = MAPPER.readValue("{\"localizedMessage\":\"ignored\",\"message\":\"Hello\"}", Throwable.class);
        assertNotNull(t);
        assertEquals("Hello", t.getMessage());
    }

    @Test
    public void testDefaultConstructorWhenNoMessage() throws Exception {
        Throwable t = MAPPER.readValue("{}", Throwable.class);
        assertNotNull(t);
        assertNull(t.getMessage());
    }
}