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
import tools.jackson.databind.cfg.EnumFeature;
import tools.jackson.databind.exc.InvalidFormatException;
import tools.jackson.databind.exc.MismatchedInputException;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.module.SimpleModule;

import com.fasterxml.jackson.annotation.JsonIdentityInfo;
import com.fasterxml.jackson.annotation.ObjectIdGenerators;

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
}