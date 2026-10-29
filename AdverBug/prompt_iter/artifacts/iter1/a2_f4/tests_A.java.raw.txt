package tools.jackson.databind.deser.impl;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import org.junit.Test;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.annotation.JsonSubTypes;
import com.fasterxml.jackson.annotation.JsonTypeInfo;
import com.fasterxml.jackson.annotation.JsonView;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;

/**
 * Tests for the completion step of external type id deserialization
 * (ExternalTypeHandler.complete), covering: basic buffering/deserialization of
 * external type ids, explicit null values, natural scalar values without type
 * ids, default implementations, missing/unknown type ids, missing values,
 * creator properties bound to the type id itself, and filtering of properties
 * by the active JsonView.
 */
public class CompleteTests
{
    private static final ObjectMapper MAPPER = JsonMapper.builder().build();

    private static final ObjectMapper STRICT_MAPPER = JsonMapper.builder()
            .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
            .build();

    private static final ObjectMapper LENIENT_MAPPER = JsonMapper.builder()
            .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
            .build();

    /*
    /**********************************************************************
    /* Helper types
    /**********************************************************************
     */

    public static class ViewIncluded {
    }

    public static class ViewExcluded {
    }

    public static class ExtValue {
        public int x;

        public ExtValue() {
        }

        public ExtValue(int x) {
            this.x = x;
        }
    }

    public static class CreatorBean {
        public final int a;
        public final ExtValue value;

        @JsonCreator(mode = JsonCreator.Mode.PROPERTIES)
        public CreatorBean(@JsonProperty("a") int a,
                @JsonProperty("value")
                @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                        include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                        property = "typeId")
                @JsonSubTypes(@JsonSubTypes.Type(value = ExtValue.class, name = "ExtValue"))
                ExtValue value) {
            this.a = a;
            this.value = value;
        }
    }

    public static class NaturalBean {
        public final Object value;

        @JsonCreator(mode = JsonCreator.Mode.PROPERTIES)
        public NaturalBean(@JsonProperty("value")
                @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                        include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                        property = "typeId")
                Object value) {
            this.value = value;
        }
    }

    public static class DefaultIdBean {
        public final ExtValue value;

        @JsonCreator(mode = JsonCreator.Mode.PROPERTIES)
        public DefaultIdBean(@JsonProperty("value")
                @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                        include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                        property = "typeId",
                        defaultImpl = ExtValue.class)
                @JsonSubTypes(@JsonSubTypes.Type(value = ExtValue.class, name = "ExtValue"))
                ExtValue value) {
            this.value = value;
        }
    }

    public static class StringIdBean {
        public final String typeId;
        public final ExtValue value;

        @JsonCreator(mode = JsonCreator.Mode.PROPERTIES)
        public StringIdBean(@JsonProperty("typeId") String typeId,
                @JsonProperty("value")
                @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                        include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                        property = "typeId")
                @JsonSubTypes(@JsonSubTypes.Type(value = ExtValue.class, name = "ExtValue"))
                ExtValue value) {
            this.typeId = typeId;
            this.value = value;
        }
    }

    public enum ExtTypeId {
        ALPHA, BRAVO
    }

    public static abstract class BaseVal {
    }

    public static class ValA extends BaseVal {
        public int a;
    }

    public static class ValB extends BaseVal {
        public int b;
    }

    public static class EnumIdBean {
        public final ExtTypeId id;
        public final BaseVal value;

        @JsonCreator(mode = JsonCreator.Mode.PROPERTIES)
        public EnumIdBean(@JsonProperty("id") ExtTypeId id,
                @JsonProperty("value")
                @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                        include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                        property = "id")
                @JsonSubTypes({
                    @JsonSubTypes.Type(value = ValA.class, name = "ALPHA"),
                    @JsonSubTypes.Type(value = ValB.class, name = "BRAVO")
                })
                BaseVal value) {
            this.id = id;
            this.value = value;
        }
    }

    public static class ViewedBean {
        public final int a;
        public final ExtValue value;

        @JsonCreator(mode = JsonCreator.Mode.PROPERTIES)
        public ViewedBean(@JsonProperty("a") int a,
                @JsonProperty("value")
                @JsonView(ViewIncluded.class)
                @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                        include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                        property = "typeId")
                @JsonSubTypes(@JsonSubTypes.Type(value = ExtValue.class, name = "ExtValue"))
                ExtValue value) {
            this.a = a;
            this.value = value;
        }
    }

    /*
    /**********************************************************************
    /* Basic functionality
    /**********************************************************************
     */

    @Test
    public void testCompleteWithTypeIdAfterValue() {
        CreatorBean bean = MAPPER.readValue(
                "{\"a\":1,\"value\":{\"x\":42},\"typeId\":\"ExtValue\"}",
                CreatorBean.class);
        assertEquals(1, bean.a);
        assertNotNull(bean.value);
        assertEquals(42, bean.value.x);
    }

    @Test
    public void testCompleteWithTypeIdBeforeValue() {
        CreatorBean bean = MAPPER.readValue(
                "{\"typeId\":\"ExtValue\",\"value\":{\"x\":7},\"a\":2}",
                CreatorBean.class);
        assertEquals(2, bean.a);
        assertNotNull(bean.value);
        assertEquals(7, bean.value.x);
    }

    @Test
    public void testCompleteWithExplicitNullValue() {
        // explicit null for the value with no type id at all must be accepted
        CreatorBean bean = MAPPER.readValue("{\"a\":3,\"value\":null}",
                CreatorBean.class);
        assertEquals(3, bean.a);
        assertNull(bean.value);
    }

    @Test
    public void testCompleteNaturalStringWithoutTypeId() {
        // natural (scalar) values must bind without any external type id
        NaturalBean bean = MAPPER.readValue("{\"value\":\"text\"}", NaturalBean.class);
        assertEquals("text", bean.value);
    }

    @Test
    public void testCompleteNaturalIntWithoutTypeId() {
        NaturalBean bean = MAPPER.readValue("{\"value\":123}", NaturalBean.class);
        assertEquals(123, bean.value);
    }

    /*
    /**********************************************************************
    /* Invalid inputs and error handling
    /**********************************************************************
     */

    @Test
    public void testCompleteMissingTypeIdForPojoFails() {
        try {
            MAPPER.readValue("{\"a\":4,\"value\":{\"x\":1}}", CreatorBean.class);
            fail("Expected an exception for missing external type id");
        } catch (JacksonException e) {
            // expected
        }
    }

    @Test
    public void testCompleteUnknownTypeIdFails() {
        try {
            MAPPER.readValue("{\"a\":1,\"value\":{\"x\":1},\"typeId\":\"Bogus\"}",
                    CreatorBean.class);
            fail("Expected an exception for unknown external type id");
        } catch (JacksonException e) {
            // expected
        }
    }

    @Test
    public void testCompleteTypeIdPresentValueMissingFailsWhenStrict() {
        try {
            STRICT_MAPPER.readValue("{\"a\":1,\"typeId\":\"ExtValue\"}", CreatorBean.class);
            fail("Expected an exception for missing value matching external type id");
        } catch (JacksonException e) {
            // expected
        }
    }

    @Test
    public void testCompleteTypeIdPresentValueMissingNullWhenLenient() {
        // with FAIL_ON_UNKNOWN_PROPERTIES disabled, absent value matching a
        // present type id must yield a null value instead of failing
        CreatorBean bean = LENIENT_MAPPER.readValue("{\"a\":1,\"typeId\":\"ExtValue\"}",
                CreatorBean.class);
        assertEquals(1, bean.a);
        assertNull(bean.value);
    }

    /*
    /**********************************************************************
    /* Default impl and creator properties for type ids
    /**********************************************************************
     */

    @Test
    public void testCompleteDefaultImplUsedWhenTypeIdMissing() {
        DefaultIdBean bean = MAPPER.readValue("{\"value\":{\"x\":9}}", DefaultIdBean.class);
        assertNotNull(bean.value);
        assertEquals(9, bean.value.x);
    }

    @Test
    public void testCompleteCreatorPropertyForTypeIdString() {
        StringIdBean bean = MAPPER.readValue(
                "{\"value\":{\"x\":5},\"typeId\":\"ExtValue\"}", StringIdBean.class);
        assertEquals("ExtValue", bean.typeId);
        assertNotNull(bean.value);
        assertEquals(5, bean.value.x);
    }

    @Test
    public void testCompleteCreatorPropertyForTypeIdEnum() {
        // non-String type id creator property: id must be deserialized via its
        // own deserializer, not assigned as a raw String
        EnumIdBean bean = MAPPER.readValue(
                "{\"value\":{\"a\":11},\"id\":\"ALPHA\"}", EnumIdBean.class);
        assertEquals(ExtTypeId.ALPHA, bean.id);
        assertTrue(bean.value instanceof ValA);
        assertEquals(11, ((ValA) bean.value).a);
    }

    /*
    /**********************************************************************
    /* Active JsonView filtering
    /**********************************************************************
     */

    @Test
    public void testViewIncludingExternalTypePropertyDeserializesValue() {
        // with a view that includes the property, normal binding must occur
        ViewedBean bean = MAPPER.readerFor(ViewedBean.class)
                .withView(ViewIncluded.class)
                .readValue("{\"a\":1,\"value\":{\"x\":42},\"typeId\":\"ExtValue\"}");
        assertEquals(1, bean.a);
        assertNotNull(bean.value);
        assertEquals(42, bean.value.x);
    }

    @Test
    public void testViewFilteredExternalTypePropertyNotBound() {
        // property filtered out by the active view must be skipped entirely:
        // the buffered value must NOT be bound even though the type id is present
        ViewedBean bean = STRICT_MAPPER.readerFor(ViewedBean.class)
                .withView(ViewExcluded.class)
                .readValue("{\"a\":1,\"value\":{\"x\":42},\"typeId\":\"ExtValue\"}");
        assertEquals(1, bean.a);
        assertNull(bean.value);
    }

    @Test
    public void testViewFilteredExternalTypePropertyMissingTypeIdDoesNotFail() {
        // filtered-out property with no type id must not be reported as missing
        ViewedBean bean = STRICT_MAPPER.readerFor(ViewedBean.class)
                .withView(ViewExcluded.class)
                .readValue("{\"a\":1,\"value\":{\"x\":42}}");
        assertEquals(1, bean.a);
        assertNull(bean.value);
    }

    @Test
    public void testViewFilteredExternalTypePropertyTypeIdOnlyDoesNotFail() {
        // filtered-out property with a type id but no value must not fail either
        ViewedBean bean = STRICT_MAPPER.readerFor(ViewedBean.class)
                .withView(ViewExcluded.class)
                .readValue("{\"a\":1,\"typeId\":\"ExtValue\"}");
        assertEquals(1, bean.a);
        assertNull(bean.value);
    }

    @Test
    public void testViewIncludingMissingValueFailsWhenStrict() {
        // property included by the view, type id present, value missing: error
        try {
            STRICT_MAPPER.readerFor(ViewedBean.class)
                    .withView(ViewIncluded.class)
                    .readValue("{\"a\":1,\"typeId\":\"ExtValue\"}");
            fail("Expected an exception for missing value matching external type id");
        } catch (JacksonException e) {
            // expected
        }
    }
}