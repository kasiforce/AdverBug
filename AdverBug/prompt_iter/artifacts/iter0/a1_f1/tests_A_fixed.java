package tools.jackson.databind.deser.jdk;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.EnumMap;
import java.util.List;

import org.junit.Test;

import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.cfg.EnumFeature;
import tools.jackson.databind.exc.InvalidFormatException;
import tools.jackson.databind.exc.MismatchedInputException;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

/**
 * Tests for EnumMapDeserializer._deserializeUsingProperties behavior: deserialization
 * of JSON objects into EnumMap instances, covering valid input, empty objects, null
 * values, unknown enum keys (strict and lenient modes), invalid values and non-object
 * input error handling.
 */
public class _deserializeUsingPropertiesTests {

    private enum Fruit {
        APPLE, BANANA, CHERRY
    }

    private final JsonMapper mapper = JsonMapper.builder().build();

    private final TypeReference<EnumMap<Fruit, Integer>> enumMapType =
            new TypeReference<EnumMap<Fruit, Integer>>() { };

    @Test
    public void testBasicEnumMapDeserialization() {
        EnumMap<Fruit, Integer> result = mapper.readValue(
                "{\"BANANA\": 2, \"APPLE\": 1, \"CHERRY\": 3}", enumMapType);

        assertNotNull(result);
        assertEquals(3, result.size());
        assertEquals(Integer.valueOf(1), result.get(Fruit.APPLE));
        assertEquals(Integer.valueOf(2), result.get(Fruit.BANANA));
        assertEquals(Integer.valueOf(3), result.get(Fruit.CHERRY));
    }

    @Test
    public void testDeserializedMapIsEnumMapWithOrdinalKeyOrder() {
        EnumMap<Fruit, Integer> result = mapper.readValue(
                "{\"CHERRY\": 3, \"APPLE\": 1, \"BANANA\": 2}", enumMapType);

        assertNotNull(result);
        assertTrue(result instanceof EnumMap<?, ?>);
        // EnumMap iterates keys in enum-declaration (ordinal) order, not JSON order
        List<Fruit> keyOrder = new ArrayList<Fruit>(result.keySet());
        assertEquals(Arrays.asList(Fruit.APPLE, Fruit.BANANA, Fruit.CHERRY), keyOrder);
    }

    @Test
    public void testEmptyObjectDeserialization() {
        EnumMap<Fruit, Integer> result = mapper.readValue("{}", enumMapType);

        assertNotNull(result);
        assertTrue(result.isEmpty());
        assertEquals(0, result.size());
    }

    @Test
    public void testNullValuesAreSkipped() {
        EnumMap<Fruit, Integer> result = mapper.readValue(
                "{\"APPLE\": null, \"BANANA\": 2}", enumMapType);

        assertNotNull(result);
        assertEquals(1, result.size());
        assertFalse(result.containsKey(Fruit.APPLE));
        assertEquals(Integer.valueOf(2), result.get(Fruit.BANANA));
    }

    @Test
    public void testUnknownEnumKeyThrowsInvalidFormatException() {
        try {
            mapper.readValue("{\"UNKNOWN\": 1}", enumMapType);
            fail("Expected InvalidFormatException for unknown enum key");
        } catch (InvalidFormatException e) {
            String msg = String.valueOf(e.getMessage());
            assertTrue("Exception message should mention the unknown key, was: " + msg,
                    msg.contains("UNKNOWN"));
        }
    }

    @Test
    public void testUnknownEnumKeyAsNullSkipsEntry() {
        JsonMapper lenientMapper = JsonMapper.builder()
                .enable(EnumFeature.READ_UNKNOWN_ENUM_VALUES_AS_NULL)
                .build();

        EnumMap<Fruit, Integer> result = lenientMapper.readValue(
                "{\"UNKNOWN\": 1, \"BANANA\": 2}", enumMapType);

        assertNotNull(result);
        assertEquals(1, result.size());
        assertFalse(result.containsValue(Integer.valueOf(1)));
        assertEquals(Integer.valueOf(2), result.get(Fruit.BANANA));
    }

    @Test
    public void testInvalidValueTypeThrowsInvalidFormatException() {
        try {
            mapper.readValue("{\"APPLE\": \"not-a-number\"}", enumMapType);
            fail("Expected InvalidFormatException for non-numeric value");
        } catch (InvalidFormatException e) {
            // expected
        }
    }

    @Test
    public void testNonObjectInputThrowsMismatchedInputException() {
        try {
            mapper.readValue("[1, 2, 3]", enumMapType);
            fail("Expected MismatchedInputException for non-object input");
        } catch (MismatchedInputException e) {
            // expected
        }
    }
}