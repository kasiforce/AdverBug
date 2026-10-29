package tools.jackson.databind.deser.jdk;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.EnumMap;
import java.util.List;

import org.junit.Test;

import tools.jackson.core.JsonParser;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.DeserializationContext;
import tools.jackson.databind.ValueDeserializer;
import tools.jackson.databind.annotation.JsonIdentityInfo;
import tools.jackson.databind.annotation.ObjectIdGenerators;
import tools.jackson.databind.cfg.EnumFeature;
import tools.jackson.databind.exc.InvalidFormatException;
import tools.jackson.databind.exc.MismatchedInputException;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.module.SimpleModule;

import static org.junit.Assert.*;

/**
 * Unit tests exercising {@code EnumMapDeserializer#deserialize} through the
 * public data-binding API (JSON to {@link java.util.EnumMap} deserialization).
 */
public class DeserializeTests
{
    private final JsonMapper mapper = new JsonMapper();

    private final JsonMapper unknownAsNullMapper = JsonMapper.builder()
            .enable(EnumFeature.READ_UNKNOWN_ENUM_VALUES_AS_NULL)
            .build();

    private final JsonMapper ctxAwareMapper = JsonMapper.builder()
            .addModule(new SimpleModule("ctx-aware")
                    .addDeserializer(CtxAware.class, new CtxAwareDeser()))
            .build();

    public enum ABC { A, B, C }

    @JsonIdentityInfo(generator = ObjectIdGenerators.IntSequenceGenerator.class, property = "@id")
    public static class IdentBean {
        public String name;
    }

    public static class CtxAware {
        public final Object owner;

        public CtxAware(Object owner) {
            this.owner = owner;
        }
    }

    public static class CtxAwareDeser extends ValueDeserializer<CtxAware> {
        @Override
        public CtxAware deserialize(JsonParser p, DeserializationContext ctxt) {
            return new CtxAware(p.currentValue());
        }
    }

    @Test
    public void testBasicDeserialization() throws Exception {
        EnumMap<ABC, Integer> result = mapper.readValue(
                "{\"C\": 30, \"A\": 10, \"B\": 20}",
                new TypeReference<EnumMap<ABC, Integer>>() { });
        assertTrue(result instanceof EnumMap);
        assertEquals(3, result.size());
        assertEquals(Integer.valueOf(10), result.get(ABC.A));
        assertEquals(Integer.valueOf(20), result.get(ABC.B));
        assertEquals(Integer.valueOf(30), result.get(ABC.C));
        // EnumMap iterates keys in natural (declaration) order
        List<ABC> keys = new ArrayList<ABC>(result.keySet());
        assertEquals(Arrays.asList(ABC.A, ABC.B, ABC.C), keys);
    }

    @Test
    public void testEmptyObjectProducesEmptyMap() throws Exception {
        EnumMap<ABC, Integer> result = mapper.readValue(
                "{}", new TypeReference<EnumMap<ABC, Integer>>() { });
        assertNotNull(result);
        assertEquals(0, result.size());
        assertTrue(result.isEmpty());
        assertEquals(new EnumMap<ABC, Integer>(ABC.class), result);
    }

    @Test
    public void testDuplicateKeysLastValueWins() throws Exception {
        EnumMap<ABC, Integer> result = mapper.readValue(
                "{\"A\": 1, \"A\": 2, \"B\": 5}",
                new TypeReference<EnumMap<ABC, Integer>>() { });
        assertEquals(2, result.size());
        assertEquals(Integer.valueOf(2), result.get(ABC.A));
        assertEquals(Integer.valueOf(5), result.get(ABC.B));
    }

    @Test
    public void testNullValuesAreSkippedByDefault() throws Exception {
        EnumMap<ABC, Integer> result = mapper.readValue(
                "{\"A\": null, \"B\": 2}",
                new TypeReference<EnumMap<ABC, Integer>>() { });
        assertEquals(1, result.size());
        assertFalse(result.containsKey(ABC.A));
        assertEquals(Integer.valueOf(2), result.get(ABC.B));
        assertFalse(result.containsValue(null));
    }

    @Test(expected = InvalidFormatException.class)
    public void testUnknownEnumKeyFailsByDefault() throws Exception {
        mapper.readValue("{\"A\": 1, \"X\": 2}",
                new TypeReference<EnumMap<ABC, Integer>>() { });
    }

    @Test
    public void testUnknownEnumKeysSkippedWhenReadAsNullEnabled() throws Exception {
        EnumMap<ABC, Integer> result = unknownAsNullMapper.readValue(
                "{\"X\": {\"deep\": true}, \"B\": 2, \"Y\": [1, 2]}",
                new TypeReference<EnumMap<ABC, Integer>>() { });
        assertEquals(1, result.size());
        assertEquals(Integer.valueOf(2), result.get(ABC.B));
        assertFalse(result.containsKey(ABC.A));
        assertFalse(result.containsKey(ABC.C));
    }

    @Test(expected = MismatchedInputException.class)
    public void testNonObjectInputReportsWrongToken() throws Exception {
        mapper.readValue("[1, 2, 3]",
                new TypeReference<EnumMap<ABC, Integer>>() { });
    }

    @Test(expected = MismatchedInputException.class)
    public void testIncompatibleValueReportsInputMismatch() throws Exception {
        mapper.readValue("{\"A\": {\"nested\": true}}",
                new TypeReference<EnumMap<ABC, Integer>>() { });
    }

    @Test
    public void testObjectIdentityReferencesAreShared() throws Exception {
        EnumMap<ABC, IdentBean> result = mapper.readValue(
                "{\"A\": {\"@id\": 1, \"name\": \"first\"}, \"B\": 1}",
                new TypeReference<EnumMap<ABC, IdentBean>>() { });
        assertEquals(2, result.size());
        assertSame(result.get(ABC.A), result.get(ABC.B));
        assertEquals("first", result.get(ABC.A).name);
    }

    @Test
    public void testForwardReferencesAreResolved() throws Exception {
        EnumMap<ABC, IdentBean> result = mapper.readValue(
                "{\"A\": 1, \"B\": {\"@id\": 1, \"name\": \"later\"}}",
                new TypeReference<EnumMap<ABC, IdentBean>>() { });
        assertEquals(2, result.size());
        assertNotNull(result.get(ABC.A));
        assertSame(result.get(ABC.A), result.get(ABC.B));
        assertEquals("later", result.get(ABC.A).name);
    }

    @Test
    public void testCurrentValueIsAssignedToResultMap() throws Exception {
        EnumMap<ABC, CtxAware> result = ctxAwareMapper.readValue(
                "{\"A\": 42}",
                new TypeReference<EnumMap<ABC, CtxAware>>() { });
        assertEquals(1, result.size());
        assertSame(result, result.get(ABC.A).owner);
    }
}package tools.jackson.databind.deser.jdk;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.EnumMap;
import java.util.List;

import org.junit.Before;
import org.junit.Test;

import tools.jackson.core.JacksonException;
import tools.jackson.core.JsonParser;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.DeserializationContext;
import tools.jackson.databind.ValueDeserializer;
import tools.jackson.databind.exc.InvalidFormatException;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.module.SimpleModule;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

/**
 * Unit tests for {@link EnumMapDeserializer}, targeting
 * {@code EnumMapDeserializer#deserialize(JsonParser, DeserializationContext, EnumMap)},
 * exercised through the public data-binding API.
 */
public class DeserializeTests
{
    private JsonMapper _mapper;

    public enum TestKey { A, B, C }

    public record PointRecord(int x, int y) { }

    public static class ProbeValue {
        private final boolean _sawEnumMapAsCurrentValue;

        public ProbeValue(boolean sawEnumMapAsCurrentValue) {
            _sawEnumMapAsCurrentValue = sawEnumMapAsCurrentValue;
        }

        public boolean sawEnumMapAsCurrentValue() {
            return _sawEnumMapAsCurrentValue;
        }
    }

    public static class ProbeValueDeserializer extends ValueDeserializer<ProbeValue> {
        @Override
        public ProbeValue deserialize(JsonParser p, DeserializationContext ctxt) {
            Object currentValue = p.currentValue();
            return new ProbeValue(currentValue instanceof EnumMap<?, ?>);
        }
    }

    @Before
    public void setUp() {
        _mapper = JsonMapper.builder().build();
    }

    @Test
    public void testBasicDeserializationPreservesEnumOrdering() throws Exception {
        EnumMap<TestKey, String> result = _mapper.readValue(
                "{\"C\": \"vc\", \"A\": \"va\", \"B\": \"vb\"}",
                new TypeReference<EnumMap<TestKey, String>>() { });

        assertEquals(3, result.size());
        assertEquals("va", result.get(TestKey.A));
        assertEquals("vb", result.get(TestKey.B));
        assertEquals("vc", result.get(TestKey.C));

        // EnumMap iterates entries in enum-declaration (ordinal) order,
        // regardless of the order used in the JSON document
        List<TestKey> expectedOrder = Arrays.asList(TestKey.A, TestKey.B, TestKey.C);
        assertEquals(expectedOrder, new ArrayList<TestKey>(result.keySet()));
    }

    @Test
    public void testEmptyObjectGivesEmptyMap() throws Exception {
        EnumMap<TestKey, String> result = _mapper.readValue(
                "{}", new TypeReference<EnumMap<TestKey, String>>() { });

        assertNotNull(result);
        assertTrue(result instanceof EnumMap);
        assertTrue(result.isEmpty());
        assertEquals(0, result.size());
    }

    @Test
    public void testDuplicateKeysLastValueWins() throws Exception {
        EnumMap<TestKey, String> result = _mapper.readValue(
                "{\"A\": \"first\", \"B\": \"b\", \"A\": \"second\"}",
                new TypeReference<EnumMap<TestKey, String>>() { });

        assertEquals(2, result.size());
        assertEquals("second", result.get(TestKey.A));
        assertEquals("b", result.get(TestKey.B));
    }

    @Test
    public void testNullValuesAreSkippedByDefault() throws Exception {
        // With the default NullValueProvider, entries whose value is
        // VALUE_NULL are not added to the resulting EnumMap
        EnumMap<TestKey, String> result = _mapper.readValue(
                "{\"A\": null, \"B\": \"bv\"}",
                new TypeReference<EnumMap<TestKey, String>>() { });

        assertEquals(1, result.size());
        assertFalse(result.containsKey(TestKey.A));
        assertEquals("bv", result.get(TestKey.B));
    }

    @Test
    public void testNumericValuesAreDeserialized() throws Exception {
        EnumMap<TestKey, Integer> result = _mapper.readValue(
                "{\"A\": 42, \"B\": 7}",
                new TypeReference<EnumMap<TestKey, Integer>>() { });

        assertEquals(2, result.size());
        assertEquals(Integer.valueOf(42), result.get(TestKey.A));
        assertEquals(Integer.valueOf(7), result.get(TestKey.B));
    }

    @Test
    public void testRecordValuesAreDeserialized() throws Exception {
        EnumMap<TestKey, PointRecord> result = _mapper.readValue(
                "{\"A\": {\"x\": 1, \"y\": 2}, \"C\": {\"x\": 3, \"y\": 4}}",
                new TypeReference<EnumMap<TestKey, PointRecord>>() { });

        assertEquals(2, result.size());
        assertEquals(1, result.get(TestKey.A).x());
        assertEquals(2, result.get(TestKey.A).y());
        assertEquals(3, result.get(TestKey.C).x());
        assertEquals(4, result.get(TestKey.C).y());
    }

    @Test(expected = InvalidFormatException.class)
    public void testUnknownEnumKeyThrowsByDefault() throws Exception {
        // "X" is not a declared enum instance name: default handling must fail
        // with a format exception instead of silently ignoring the entry
        _mapper.readValue("{\"X\": \"xv\", \"A\": \"av\"}",
                new TypeReference<EnumMap<TestKey, String>>() { });
    }

    @Test(expected = JacksonException.class)
    public void testScalarRootValueFails() throws Exception {
        // Root token is VALUE_STRING, not START_OBJECT/PROPERTY_NAME:
        // must report a wrong-token exception
        _mapper.readValue("\"not-an-object\"",
                new TypeReference<EnumMap<TestKey, String>>() { });
    }

    @Test
    public void testCurrentValueIsAssignedForCustomValueDeserializers() throws Exception {
        // [databind#631]: the EnumMap being populated must be assigned as the
        // parser's current value so custom value deserializers can access it
        SimpleModule module = new SimpleModule("probe-module");
        module.addDeserializer(ProbeValue.class, new ProbeValueDeserializer());
        JsonMapper mapper = JsonMapper.builder()
                .addModule(module)
                .build();

        EnumMap<TestKey, ProbeValue> result = mapper.readValue(
                "{\"A\": \"a\", \"B\": \"b\"}",
                new TypeReference<EnumMap<TestKey, ProbeValue>>() { });

        assertEquals(2, result.size());
        assertTrue(result.get(TestKey.A).sawEnumMapAsCurrentValue());
        assertTrue(result.get(TestKey.B).sawEnumMapAsCurrentValue());
    }
}