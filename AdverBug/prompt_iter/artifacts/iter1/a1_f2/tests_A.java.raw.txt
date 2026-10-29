package tools.jackson.databind.deser.jdk;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import java.util.EnumMap;

import org.junit.Test;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.JavaType;
import tools.jackson.databind.json.JsonMapper;

public class DeserializeTests
{
    enum Color {
        RED, GREEN, BLUE
    }

    static class Point {
        public int x;
        public int y;
    }

    static class Holder {
        public EnumMap<Color, String> colors;
    }

    private final JsonMapper MAPPER = JsonMapper.builder().build();

    @SuppressWarnings("unchecked")
    private EnumMap<Color, String> readEnumMap(String json) {
        JavaType type = MAPPER.getTypeFactory()
                .constructMapType(EnumMap.class, Color.class, String.class);
        return (EnumMap<Color, String>) MAPPER.readValue(json, type);
    }

    // Basic functionality

    @Test
    public void testBasicEnumMapDeserialization() throws Exception {
        EnumMap<Color, String> result = readEnumMap("{\"RED\":\"red\",\"GREEN\":\"green\"}");
        assertNotNull(result);
        assertEquals(2, result.size());
        assertEquals("red", result.get(Color.RED));
        assertEquals("green", result.get(Color.GREEN));
        assertNull(result.get(Color.BLUE));
    }

    @Test
    public void testEmptyObjectDeserializesToEmptyEnumMap() throws Exception {
        EnumMap<Color, String> result = readEnumMap("{}");
        assertNotNull(result);
        assertEquals(0, result.size());
    }

    @Test
    public void testAllEnumConstantsUsedAsKeys() throws Exception {
        EnumMap<Color, String> result = readEnumMap("{\"RED\":\"r\",\"GREEN\":\"g\",\"BLUE\":\"b\"}");
        assertEquals(3, result.size());
        assertEquals("r", result.get(Color.RED));
        assertEquals("g", result.get(Color.GREEN));
        assertEquals("b", result.get(Color.BLUE));
    }

    @Test
    public void testDuplicateKeysKeepLastValue() throws Exception {
        EnumMap<Color, String> result = readEnumMap("{\"RED\":\"first\",\"RED\":\"second\"}");
        assertEquals(1, result.size());
        assertEquals("second", result.get(Color.RED));
    }

    @Test
    public void testWhitespaceInJsonIsIgnored() throws Exception {
        EnumMap<Color, String> result = readEnumMap("  {  \"RED\"  :  \"red\"  }  ");
        assertEquals(1, result.size());
        assertEquals("red", result.get(Color.RED));
    }

    // Null-value handling

    @Test
    public void testExplicitNullValueStoredAsNullEntry() throws Exception {
        EnumMap<Color, String> result = readEnumMap("{\"RED\":null}");
        assertEquals(1, result.size());
        assertTrue(result.containsKey(Color.RED));
        assertNull(result.get(Color.RED));
    }

    @Test
    public void testNullValueDoesNotAffectOtherEntries() throws Exception {
        EnumMap<Color, String> result =
                readEnumMap("{\"RED\":\"rojo\",\"GREEN\":null,\"BLUE\":\"azul\"}");
        assertEquals(3, result.size());
        assertEquals("rojo", result.get(Color.RED));
        assertTrue(result.containsKey(Color.GREEN));
        assertNull(result.get(Color.GREEN));
        assertEquals("azul", result.get(Color.BLUE));
    }

    // Invalid input and error handling

    @Test
    public void testUnknownEnumKeyRejectedByDefault() throws Exception {
        try {
            readEnumMap("{\"PINK\":\"pink\"}");
            fail("Deserializing an unknown enum key should fail by default");
        } catch (JacksonException expected) {
            // expected: unknown enum key cannot be mapped to an EnumMap key
        }
    }

    @Test
    public void testEnumKeyMatchingIsCaseSensitive() throws Exception {
        try {
            readEnumMap("{\"red\":\"value\"}");
            fail("Enum key names should be matched case-sensitively by default");
        } catch (JacksonException expected) {
            // expected: 'red' does not match declared constant RED
        }
    }

    @Test
    public void testNonObjectJsonRejected() throws Exception {
        try {
            readEnumMap("[\"RED\",\"GREEN\"]");
            fail("Deserializing a JSON array into an EnumMap should fail");
        } catch (JacksonException expected) {
            // expected: parser must point to START_OBJECT / PROPERTY_NAME
        }
    }

    @Test
    public void testScalarJsonRejected() throws Exception {
        try {
            readEnumMap("42");
            fail("Deserializing a JSON scalar into an EnumMap should fail");
        } catch (JacksonException expected) {
            // expected: parser must point to START_OBJECT / PROPERTY_NAME
        }
    }

    // Other value types and deserialization contexts

    @Test
    public void testIntegerValuesEnumMap() throws Exception {
        JavaType type = MAPPER.getTypeFactory()
                .constructMapType(EnumMap.class, Color.class, Integer.class);
        @SuppressWarnings("unchecked")
        EnumMap<Color, Integer> result =
                (EnumMap<Color, Integer>) MAPPER.readValue("{\"RED\":1,\"GREEN\":2,\"BLUE\":3}", type);
        assertEquals(3, result.size());
        assertEquals(Integer.valueOf(1), result.get(Color.RED));
        assertEquals(Integer.valueOf(2), result.get(Color.GREEN));
        assertEquals(Integer.valueOf(3), result.get(Color.BLUE));
    }

    @Test
    public void testPojoValuesEnumMap() throws Exception {
        JavaType type = MAPPER.getTypeFactory()
                .constructMapType(EnumMap.class, Color.class, Point.class);
        @SuppressWarnings("unchecked")
        EnumMap<Color, Point> result =
                (EnumMap<Color, Point>) MAPPER.readValue("{\"RED\":{\"x\":1,\"y\":2}}", type);
        assertEquals(1, result.size());
        Point point = result.get(Color.RED);
        assertNotNull(point);
        assertEquals(1, point.x);
        assertEquals(2, point.y);
    }

    @Test
    public void testEnumMapAsBeanProperty() throws Exception {
        Holder holder = MAPPER.readValue(
                "{\"colors\":{\"RED\":\"red\",\"BLUE\":\"blue\"}}", Holder.class);
        assertNotNull(holder.colors);
        assertEquals(2, holder.colors.size());
        assertEquals("red", holder.colors.get(Color.RED));
        assertEquals("blue", holder.colors.get(Color.BLUE));
    }

    @Test
    public void testRepeatedDeserializationYieldsEqualResults() throws Exception {
        String json = "{\"RED\":\"red\",\"GREEN\":\"green\"}";
        EnumMap<Color, String> first = readEnumMap(json);
        EnumMap<Color, String> second = readEnumMap(json);
        assertEquals(first, second);
        assertEquals(2, second.size());
    }
}