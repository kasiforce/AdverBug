package tools.jackson.databind.deser.impl;

import org.junit.Test;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.annotation.JsonSubTypes;
import com.fasterxml.jackson.annotation.JsonTypeInfo;
import com.fasterxml.jackson.annotation.JsonTypeName;
import com.fasterxml.jackson.annotation.JsonView;

import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.exc.MismatchedInputException;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

/**
 * Tests for {@code ExternalTypeHandler.complete(...)}, exercised end-to-end
 * through data-binding of beans with {@code @JsonTypeInfo} external type ids
 * and property-based creators. Covers buffering of type ids and values,
 * ordering, missing type ids and missing values, default implementations,
 * type id exposed as a creator property, and filtering by active
 * {@code JsonView}.
 */
public class CompleteTests
{
    private final ObjectMapper MAPPER = JsonMapper.builder().build();

    /*
    /**********************************************************************
    /* Helper types
    /**********************************************************************
     */

    @JsonTypeInfo(use = JsonTypeInfo.Id.NAME, include = JsonTypeInfo.As.PROPERTY,
            property = "type")
    @JsonSubTypes({
        @JsonSubTypes.Type(value = ImplA.class, name = "a"),
        @JsonSubTypes.Type(value = ImplB.class, name = "b")
    })
    public static abstract class Base { }

    @JsonTypeName("a")
    public static class ImplA extends Base {
        public int a;
    }

    @JsonTypeName("b")
    public static class ImplB extends Base {
        public int b;
    }

    // Bean with external type id on a creator property
    public static class CreatorBean {
        public final int id;

        @JsonTypeInfo(use = JsonTypeInfo.Id.NAME, include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                property = "type")
        public final Base value;

        @JsonCreator
        public CreatorBean(@JsonProperty("id") int id,
                @JsonProperty("value") Base value) {
            this.id = id;
            this.value = value;
        }
    }

    // Bean with external type id on a creator property, limited to a view
    public interface ViewA { }
    public interface ViewB { }

    public static class ViewedCreatorBean {
        public final int id;

        @JsonView(ViewA.class)
        @JsonTypeInfo(use = JsonTypeInfo.Id.NAME, include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                property = "type")
        public final Base value;

        @JsonCreator
        public ViewedCreatorBean(@JsonProperty("id") int id,
                @JsonProperty("value") Base value) {
            this.id = id;
            this.value = value;
        }
    }

    // Bean with external type id on a non-creator property
    public static class MixedBean {
        public final int id;

        @JsonTypeInfo(use = JsonTypeInfo.Id.NAME, include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                property = "type")
        public Base value;

        @JsonCreator
        public MixedBean(@JsonProperty("id") int id) {
            this.id = id;
        }
    }

    // Bean where external type id is also exposed as a creator property
    public static class TypeIdCreatorBean {
        public final String type;

        @JsonTypeInfo(use = JsonTypeInfo.Id.NAME, include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                property = "type", visible = true)
        public final Base value;

        @JsonCreator
        public TypeIdCreatorBean(@JsonProperty("type") String type,
                @JsonProperty("value") Base value) {
            this.type = type;
            this.value = value;
        }
    }

    // Like TypeIdCreatorBean but with non-String type id creator property
    public enum ExtTypeId { a, b }

    public static class EnumTypeIdCreatorBean {
        public final ExtTypeId type;

        @JsonTypeInfo(use = JsonTypeInfo.Id.NAME, include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                property = "type", visible = true)
        public final Base value;

        @JsonCreator
        public EnumTypeIdCreatorBean(@JsonProperty("type") ExtTypeId type,
                @JsonProperty("value") Base value) {
            this.type = type;
            this.value = value;
        }
    }

    // Bean with 'defaultImpl' fallback for missing external type id
    public static class DefaultImplCreatorBean {
        public final int id;

        @JsonTypeInfo(use = JsonTypeInfo.Id.NAME, include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                property = "type", defaultImpl = ImplB.class)
        public final Base value;

        @JsonCreator
        public DefaultImplCreatorBean(@JsonProperty("id") int id,
                @JsonProperty("value") Base value) {
            this.id = id;
            this.value = value;
        }
    }

    /*
    /**********************************************************************
    /* Tests
    /**********************************************************************
     */

    // Basic case: creator property with external type id, type id before value
    @Test
    public void testExternalTypeIdWithCreatorProperty() {
        CreatorBean bean = MAPPER.readValue(
                "{\"id\":1,\"type\":\"a\",\"value\":{\"a\":13}}", CreatorBean.class);
        assertEquals(1, bean.id);
        assertTrue(bean.value instanceof ImplA);
        assertEquals(13, ((ImplA) bean.value).a);
    }

    // Same as above but with value before type id (order must not matter)
    @Test
    public void testExternalTypeIdAfterValue() {
        CreatorBean bean = MAPPER.readValue(
                "{\"value\":{\"a\":13},\"type\":\"a\",\"id\":1}", CreatorBean.class);
        assertEquals(1, bean.id);
        assertTrue(bean.value instanceof ImplA);
        assertEquals(13, ((ImplA) bean.value).a);
    }

    // Missing external type id without defaultImpl: must fail
    @Test(expected = MismatchedInputException.class)
    public void testMissingExternalTypeIdFails() {
        MAPPER.readValue("{\"id\":1,\"value\":{\"a\":13}}", CreatorBean.class);
    }

    // [databind#94]: missing type id falls back to 'defaultImpl'
    @Test
    public void testDefaultImplUsedWhenTypeIdMissing() {
        DefaultImplCreatorBean bean = MAPPER.readValue(
                "{\"id\":1,\"value\":{\"b\":5}}", DefaultImplCreatorBean.class);
        assertEquals(1, bean.id);
        assertTrue(bean.value instanceof ImplB);
        assertEquals(5, ((ImplB) bean.value).b);
    }

    // [databind#3533]: type id present but value property missing: default
    // instance of the subtype is created instead
    @Test
    public void testMissingValueWithTypeUsesEmptyValue() {
        ObjectMapper mapper = JsonMapper.builder()
                .disable(DeserializationFeature.FAIL_ON_MISSING_EXTERNAL_TYPE_ID_PROPERTY)
                .build();
        CreatorBean bean = mapper.readValue("{\"id\":1,\"type\":\"a\"}", CreatorBean.class);
        assertEquals(1, bean.id);
        assertNotNull(bean.value);
        assertTrue(bean.value instanceof ImplA);
        assertEquals(0, ((ImplA) bean.value).a);
    }

    // Same as above but with the failing feature explicitly enabled
    @Test(expected = MismatchedInputException.class)
    public void testMissingValueWithTypeFailsWhenFeatureEnabled() {
        ObjectMapper mapper = JsonMapper.builder()
                .enable(DeserializationFeature.FAIL_ON_MISSING_EXTERNAL_TYPE_ID_PROPERTY)
                .build();
        mapper.readValue("{\"id\":1,\"type\":\"a\"}", CreatorBean.class);
    }

    // Missing both type id and value: property simply skipped
    @Test
    public void testMissingBothTypeIdAndValueSkipped() {
        CreatorBean bean = MAPPER.readValue("{\"id\":1}", CreatorBean.class);
        assertEquals(1, bean.id);
        assertNull(bean.value);
    }

    // Explicit nulls for both type id and value must be accepted too
    @Test
    public void testExplicitNullTypeIdAndValueSkipped() {
        CreatorBean bean = MAPPER.readValue(
                "{\"id\":1,\"type\":null,\"value\":null}", CreatorBean.class);
        assertEquals(1, bean.id);
        assertNull(bean.value);
    }

    // [databind#999]: external type id also bound to a String creator property
    @Test
    public void testExternalTypeIdAsCreatorProperty() {
        TypeIdCreatorBean bean = MAPPER.readValue(
                "{\"type\":\"a\",\"value\":{\"a\":13}}", TypeIdCreatorBean.class);
        assertEquals("a", bean.type);
        assertTrue(bean.value instanceof ImplA);
        assertEquals(13, ((ImplA) bean.value).a);
    }

    // [databind#1328]: external type id bound to a non-String creator property
    @Test
    public void testEnumExternalTypeIdAsCreatorProperty() {
        EnumTypeIdCreatorBean bean = MAPPER.readValue(
                "{\"type\":\"a\",\"value\":{\"a\":13}}", EnumTypeIdCreatorBean.class);
        assertEquals(ExtTypeId.a, bean.type);
        assertTrue(bean.value instanceof ImplA);
        assertEquals(13, ((ImplA) bean.value).a);
    }

    // External type id property that is not a creator property must be
    // assigned to the bean built by the creator
    @Test
    public void testNonCreatorExternalTypeIdProperty() {
        MixedBean bean = MAPPER.readValue(
                "{\"id\":1,\"type\":\"a\",\"value\":{\"a\":13}}", MixedBean.class);
        assertEquals(1, bean.id);
        assertTrue(bean.value instanceof ImplA);
        assertEquals(13, ((ImplA) bean.value).a);
    }

    // Property visible in the active view is deserialized normally
    @Test
    public void testExternalTypeIdVisibleInView() {
        ViewedCreatorBean bean = MAPPER.readerFor(ViewedCreatorBean.class)
                .withView(ViewA.class)
                .readValue("{\"id\":1,\"type\":\"a\",\"value\":{\"a\":13}}");
        assertEquals(1, bean.id);
        assertTrue(bean.value instanceof ImplA);
        assertEquals(13, ((ImplA) bean.value).a);
    }

    // [databind#6055]: property filtered out by the active view is skipped
    // entirely; value left null, no failure reported despite buffered type id
    // and value being present
    @Test
    public void testExternalTypeIdFilteredOutByView() {
        ViewedCreatorBean bean = MAPPER.readerFor(ViewedCreatorBean.class)
                .withView(ViewB.class)
                .readValue("{\"id\":1,\"type\":\"a\",\"value\":{\"a\":13}}");
        assertEquals(1, bean.id);
        assertNull(bean.value);
    }
}