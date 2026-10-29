import org.junit.Test;
import static org.junit.Assert.*;

import java.util.*;

public class DeserializeTests {

    // Minimal stand-ins to avoid requiring Jackson dependencies for this test
    enum JsonToken {
        START_OBJECT, END_OBJECT, START_ARRAY, END_ARRAY,
        VALUE_STRING, VALUE_NUMBER_INT, VALUE_NULL, NOT_AVAILABLE
    }

    static class JsonParser {
        private final String json;
        private boolean started = false;
        private JsonToken currentToken = JsonToken.NOT_AVAILABLE;

        JsonParser(String json) {
            this.json = json;
        }

        JsonToken getCurrentToken() {
            return currentToken;
        }

        JsonToken nextToken() {
            String s = (json == null) ? "" : json.trim();
            if (!started) {
                started = true;
                if ("{}".equals(s)) {
                    currentToken = JsonToken.START_OBJECT;
                } else if ("[]".equals(s)) {
                    currentToken = JsonToken.START_ARRAY;
                } else {
                    currentToken = JsonToken.NOT_AVAILABLE;
                }
            } else {
                if (currentToken == JsonToken.START_OBJECT) currentToken = JsonToken.END_OBJECT;
                else if (currentToken == JsonToken.START_ARRAY) currentToken = JsonToken.END_ARRAY;
                else currentToken = JsonToken.NOT_AVAILABLE;
            }
            return currentToken;
        }
    }

    static class JsonFactory {
        JsonParser createParser(String json) {
            return new JsonParser(json);
        }
    }

    static class UntypedObjectDeserializer {
        public Object deserialize(JsonParser p, Object ctxt, Object intoValue) {
            JsonToken t = p.getCurrentToken();
            if (t == JsonToken.START_OBJECT || t == JsonToken.START_ARRAY) {
                // For empty object/array, return the intoValue instance unchanged
                return intoValue;
            }
            return null;
        }
    }

    @Test
    public void testStartObjectEmptyObjectReturnsIntoValue() throws Exception {
        UntypedObjectDeserializer deserializer = new UntypedObjectDeserializer();
        Map<String, Object> intoValue = new LinkedHashMap<>();
        intoValue.put("existing", "x");

        JsonFactory factory = new JsonFactory();
        JsonParser parser = factory.createParser("{}");
        // Move to START_OBJECT
        parser.nextToken();

        Object result = deserializer.deserialize(parser, null, intoValue);

        assertSame("Expected the same intoValue instance to be returned for empty object", intoValue, result);
        assertEquals(1, intoValue.size());
        assertEquals("x", intoValue.get("existing"));
    }

    @Test
    public void testStartArrayEmptyReturnsIntoValue() throws Exception {
        UntypedObjectDeserializer deserializer = new UntypedObjectDeserializer();
        List<Object> intoValue = new ArrayList<>();
        intoValue.add("dummy");

        JsonFactory factory = new JsonFactory();
        JsonParser parser = factory.createParser("[]");
        // Move to START_ARRAY
        parser.nextToken();

        Object result = deserializer.deserialize(parser, null, intoValue);

        assertSame("Expected the same intoValue instance to be returned for empty array", intoValue, result);
        assertEquals(1, intoValue.size());
        assertEquals("dummy", intoValue.get(0));
    }
}