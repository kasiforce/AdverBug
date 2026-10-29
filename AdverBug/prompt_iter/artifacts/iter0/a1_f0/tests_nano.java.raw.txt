package tools.jackson.databind.deser.jdk;

import org.junit.Test;
import static org.junit.Assert.*;

import tools.jackson.databind.ObjectMapper;
import tools.jackson.core.JacksonException;
import com.fasterxml.jackson.annotation.JsonCreator;

public class DeserializeTests {

    // Enum with a delegating JsonCreator that takes a String and returns the corresponding value
    public enum Color {
        RED, BLUE;

        @JsonCreator(mode = JsonCreator.Mode.DELEGATING)
        public static Color fromString(String s) {
            return Color.valueOf(s);
        }
    }

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Test
    public void testDeserializeBlueFromString() throws Exception {
        Color color = MAPPER.readValue("\"BLUE\"", Color.class);
        assertEquals(Color.BLUE, color);
    }

    @Test
    public void testDeserializeRedFromString() throws Exception {
        Color color = MAPPER.readValue("\"RED\"", Color.class);
        assertEquals(Color.RED, color);
    }

    @Test(expected = JacksonException.class)
    public void testDeserializeUnknownEnumValueThrows() throws Exception {
        MAPPER.readValue("\"GREEN\"", Color.class);
    }

    @Test(expected = JacksonException.class)
    public void testDeserializeNumericValueThrows() throws Exception {
        MAPPER.readValue("1", Color.class);
    }
}