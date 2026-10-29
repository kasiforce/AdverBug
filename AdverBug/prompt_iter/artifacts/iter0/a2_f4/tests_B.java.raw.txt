package tools.jackson.databind.deser.impl;

import org.junit.Test;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.annotation.JsonSubTypes;
import com.fasterxml.jackson.annotation.JsonTypeInfo;
import com.fasterxml.jackson.annotation.JsonTypeInfo.As;
import com.fasterxml.jackson.annotation.JsonTypeInfo.Id;
import com.fasterxml.jackson.annotation.JsonView;

import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.exc.MismatchedInputException;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

/**
 * Tests for the creator-based {@code ExternalTypeHandler.complete(...)}: deserialization
 * of beans that use external type ids together with {@code @JsonCreator} constructors.
 * Covers basic functionality, missing/null type ids and values, natural (scalar) types,
 * defaultImpl, creator properties for the type id itself, active {@code @JsonView}
 * filtering, and non-creator external type id properties.
 */
public class CompleteTests
{
    private final ObjectMapper mapper = new JsonMapper();

    // View markers
    interface ViewA { }
    interface ViewB { }

    static class ValueImpl {
        public int x;

        public ValueImpl() { }

        public ValueImpl(int x) { this.x = x; }
    }

    static class BasicCreatorBean {
        final Object value;
        final String type;

        @JsonCreator
        BasicCreatorBean(@JsonProperty("value")
                @JsonTypeInfo(use = Id.NAME, include = As.EXTERNAL_PROPERTY, property = "type")
                @JsonSubTypes({ @JsonSubTypes.Type(value = ValueImpl.class, name = "impl") })
                Object value,
                @JsonProperty("type") String type) {
            this.value = value;
            this.type = type;
        }
    }

    static class DefaultImplCreatorBean {
        final Object value;
        final String type;

        @JsonCreator
        DefaultImplCreatorBean(@JsonProperty("value")
                @JsonTypeInfo(use = Id.NAME, include = As.EXTERNAL_PROPERTY, property = "type",
                        defaultImpl = ValueImpl.class)
                @JsonSubTypes({ @JsonSubTypes.Type(value = ValueImpl.class, name = "impl") })
                Object value,
                @JsonProperty("type") String type) {
            this.value = value;
            this.type = type;
        }
    }

    // For natural (scalar) types no type id is included in JSON ([databind#3786])
    static class NaturalStringCreatorBean {
        final String value;
        final String vtype;

        @JsonCreator
        NaturalStringCreatorBean(@JsonProperty("value")
                @JsonTypeInfo(use = Id.NAME, include = As.EXTERNAL_PROPERTY, property = "vtype")
                @JsonSubTypes({ @JsonSubTypes.Type(value = String.class, name = "str") })
                String value,
                @JsonProperty("vtype") String vtype) {
            this.value = value;
            this.vtype = vtype;
        }
    }

    static class NaturalIntCreatorBean {
        final Integer value;
        final String vtype;

        @JsonCreator
        NaturalIntCreatorBean(@JsonProperty("value")
                @JsonTypeInfo(use = Id.NAME, include = As.EXTERNAL_PROPERTY, property = "vtype")
                @JsonSubTypes({ @JsonSubTypes.Type(value = Integer.class, name = "int") })
                Integer value,
                @JsonProperty("vtype") String vtype) {
            this.value = value;
            this.vtype = vtype;
        }
    }

    // Type id itself bound to a non-String creator property ([databind#999], [databind#1328])
    enum ExtTypeEnum { IMPL }

    static class EnumTypeCreatorBean {
        final Object value;
        final ExtTypeEnum vtype;

        @JsonCreator
        EnumTypeCreatorBean(@JsonProperty("value")
                @JsonTypeInfo(use = Id.NAME, include = As.EXTERNAL_PROPERTY, property = "vtype")
                @JsonSubTypes({ @JsonSubTypes.Type(value = ValueImpl.class, name = "IMPL") })
                Object value,
                @JsonProperty("vtype") ExtTypeEnum vtype) {
            this.value = value;
            this.vtype = vtype;
        }
    }

    // External type id property filtered out by the active view ([databind#6055])
    static class ViewedCreatorBean {
        final String name;
        final Object value;
        final String vtype;

        @JsonCreator
        ViewedCreatorBean(@JsonProperty("name") String name,
                @JsonProperty("value")
                        @JsonTypeInfo(use = Id.NAME, include = As.EXTERNAL_PROPERTY, property = "vtype")
                        @JsonSubTypes({ @JsonSubTypes.Type(value = ValueImpl.class, name = "impl") })
                        @JsonView(ViewB.class)
                        Object value,
                @JsonProperty("vtype") @JsonView(ViewB.class) String vtype) {
            this.name = name;
            this.value = value;
            this.vtype = vtype;
        }
    }

    // Non-creator external type id property on a creator-based bean
    static class MixedBean {
        final String name;

        @JsonTypeInfo(use = Id.NAME, include = As.EXTERNAL_PROPERTY, property = "vtype")
        @JsonSubTypes({ @JsonSubTypes.Type(value = ValueImpl.class, name = "impl") })
        public Object value;

        @JsonCreator
        MixedBean(@JsonProperty("name") String name) {
            this.name = name;
        }
    }

    @Test
    public void testBasicExternalTypeIdWithCreator() throws Exception {
        BasicCreatorBean result = mapper.readValue(
                "{\"type\":\"impl\",\"value\":{\"x\":3}}", BasicCreatorBean.class);
        assertTrue(result.value instanceof ValueImpl);
        assertEquals(3, ((ValueImpl) result.value).x);
        assertEquals("impl", result.type);
    }

    @Test
    public void testValueBeforeType() throws Exception {
        // Order of buffered value vs type id must not matter
        BasicCreatorBean result = mapper.readValue(
                "{\"value\":{\"x\":1},\"type\":\"impl\"}", BasicCreatorBean.class);
        assertTrue(result.value instanceof ValueImpl);
        assertEquals(1, ((ValueImpl) result.value).x);
        assertEquals("impl", result.type);
    }

    @Test
    public void testExplicitNullValueWithType() throws Exception {
        BasicCreatorBean result = mapper.readValue(
                "{\"type\":\"impl\",\"value\":null}", BasicCreatorBean.class);
        assertNull(result.value);
        assertEquals("impl", result.type);
    }

    @Test
    public void testNullValueWithoutType() throws Exception {
        // Explicit null for value with missing type id is accepted, no error
        BasicCreatorBean result = mapper.readValue("{\"value\":null}", BasicCreatorBean.class);
        assertNull(result.value);
        assertNull(result.type);
    }

    @Test
    public void testMissingBothTypeIdAndValue() throws Exception {
        // Missing both type id and property is allowed
        BasicCreatorBean result = mapper.readValue("{}", BasicCreatorBean.class);
        assertNull(result.value);
        assertNull(result.type);
    }

    @Test
    public void testMissingTypeIdForStructuredValueFails() throws Exception {
        // Structured (non-scalar) value without type id and without defaultImpl must fail
        try {
            mapper.readValue("{\"value\":{\"x\":3}}", BasicCreatorBean.class);
            fail("Should not accept missing external type id");
        } catch (MismatchedInputException e) {
            assertTrue(e.getMessage().contains("Missing external type id"));
        }
    }

    @Test
    public void testMissingValuePropertyWithTypeIdPresent() throws Exception {
        // By default, absent value matching a present type id is tolerated
        BasicCreatorBean result = mapper.readValue("{\"type\":\"impl\"}", BasicCreatorBean.class);
        assertEquals("impl", result.type);

        // With FAIL_ON_MISSING_EXTERNAL_TYPE_ID_PROPERTY enabled it is an error
        ObjectMapper strict = JsonMapper.builder()
                .enable(DeserializationFeature.FAIL_ON_MISSING_EXTERNAL_TYPE_ID_PROPERTY)
                .build();
        try {
            strict.readValue("{\"type\":\"impl\"}", BasicCreatorBean.class);
            fail("Should not accept missing value for external type id");
        } catch (MismatchedInputException e) {
            assertTrue(e.getMessage().contains("Missing property"));
        }
    }

    @Test
    public void testBothTypeAndValueMissingWithStrictFeature() throws Exception {
        // If neither type id nor value is buffered, property is skipped even in strict mode
        ObjectMapper strict = JsonMapper.builder()
                .enable(DeserializationFeature.FAIL_ON_MISSING_EXTERNAL_TYPE_ID_PROPERTY)
                .build();
        BasicCreatorBean result = strict.readValue("{}", BasicCreatorBean.class);
        assertNull(result.value);
        assertNull(result.type);
    }

    @Test
    public void testDefaultImplUsedWhenTypeIdMissing() throws Exception {
        // [databind#94]: defaultImpl used when external type id is missing
        DefaultImplCreatorBean result = mapper.readValue(
                "{\"value\":{\"x\":7}}", DefaultImplCreatorBean.class);
        assertTrue(result.value instanceof ValueImpl);
        assertEquals(7, ((ValueImpl) result.value).x);
        assertNull(result.type);
    }

    @Test
    public void testNaturalStringWithoutTypeId() throws Exception {
        // [databind#3786]: scalar natural value does not need external type id
        NaturalStringCreatorBean result = mapper.readValue(
                "{\"value\":\"foo\"}", NaturalStringCreatorBean.class);
        assertEquals("foo", result.value);
        assertNull(result.vtype);
    }

    @Test
    public void testNaturalStringWithTypeId() throws Exception {
        NaturalStringCreatorBean result = mapper.readValue(
                "{\"vtype\":\"str\",\"value\":\"foo\"}", NaturalStringCreatorBean.class);
        assertEquals("foo", result.value);
        assertEquals("str", result.vtype);
    }

    @Test
    public void testNaturalIntegerWithoutTypeId() throws Exception {
        NaturalIntCreatorBean result = mapper.readValue(
                "{\"value\":42}", NaturalIntCreatorBean.class);
        assertEquals(Integer.valueOf(42), result.value);
        assertNull(result.vtype);
    }

    @Test
    public void testNonStringCreatorTypeIdProperty() throws Exception {
        // [databind#999]/[databind#1328]: type id bound to non-String creator property
        EnumTypeCreatorBean result = mapper.readValue(
                "{\"vtype\":\"IMPL\",\"value\":{\"x\":5}}", EnumTypeCreatorBean.class);
        assertEquals(ExtTypeEnum.IMPL, result.vtype);
        assertTrue(result.value instanceof ValueImpl);
        assertEquals(5, ((ValueImpl) result.value).x);
    }

    @Test
    public void testViewFilteredExternalTypeIdIsSkipped() throws Exception {
        // [databind#6055]: property filtered out by active view is skipped entirely:
        // buffered value must not be bound, no error despite missing type id
        ViewedCreatorBean result = mapper.readerFor(ViewedCreatorBean.class)
                .withView(ViewA.class)
                .readValue("{\"name\":\"bob\",\"vtype\":\"impl\",\"value\":{\"x\":3}}");
        assertEquals("bob", result.name);
        assertNull(result.value);
        assertNull(result.vtype);
    }

    @Test
    public void testViewFilteredExternalTypeIdWithoutTypeId() throws Exception {
        // View-filtered property must not trigger "missing external type id" error
        ViewedCreatorBean result = mapper.readerFor(ViewedCreatorBean.class)
                .withView(ViewA.class)
                .readValue("{\"name\":\"bob\",\"value\":{\"x\":3}}");
        assertEquals("bob", result.name);
        assertNull(result.value);
        assertNull(result.vtype);
    }

    @Test
    public void testViewIncludedExternalTypeIdDeserialized() throws Exception {
        // With the including view, external type id works normally
        ViewedCreatorBean result = mapper.readerFor(ViewedCreatorBean.class)
                .withView(ViewB.class)
                .readValue("{\"name\":\"bob\",\"vtype\":\"impl\",\"value\":{\"x\":3}}");
        assertEquals("bob", result.name);
        assertTrue(result.value instanceof ValueImpl);
        assertEquals(3, ((ValueImpl) result.value).x);
        assertEquals("impl", result.vtype);
    }

    @Test
    public void testNonCreatorExternalTypeIdPropertyWithCreator() throws Exception {
        // Non-creator external type id property is assigned after creator-built bean
        MixedBean result = mapper.readValue(
                "{\"name\":\"bob\",\"vtype\":\"impl\",\"value\":{\"x\":9}}", MixedBean.class);
        assertEquals("bob", result.name);
        assertTrue(result.value instanceof ValueImpl);
        assertEquals(9, ((ValueImpl) result.value).x);
    }
}