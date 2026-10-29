package tools.jackson.databind.deser.impl;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import org.junit.Test;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.annotation.JsonSubTypes;
import com.fasterxml.jackson.annotation.JsonTypeInfo;
import com.fasterxml.jackson.annotation.JsonTypeName;
import com.fasterxml.jackson.annotation.JsonView;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.json.JsonMapper;

/**
 * End-to-end tests for the creator-property-based
 * {@code ExternalTypeHandler.complete(JsonParser, DeserializationContext,
 * PropertyValueBuffer, PropertyBasedCreator)} method. All beans below use
 * property-based creators together with external type ids
 * ({@code JsonTypeInfo.As.EXTERNAL_PROPERTY}) so that deserialization is
 * completed by the creator-based {@code complete()} method.
 *
 * Covered behaviors: basic external type id binding (type id before and after
 * the value property); type id exposed as a creator property ([databind#999]);
 * non-String type id creator properties ([databind#1328]); non-creator
 * external properties assigned after bean construction; error reporting for
 * missing external type ids; defaultImpl fallback ([databind#94]); natural
 * scalar values without type ids ([databind#3786]); explicit null values;
 * absent value and type id; present type id with missing value under
 * FAIL_ON_MISSING_EXTERNAL_TYPE_ID_PROPERTY ([databind#3533]); and
 * view-filtered external type id properties ([databind#6055]).
 */
public class CompleteTests
{
    private static final JsonMapper MAPPER = JsonMapper.builder().build();

    private static final JsonMapper STRICT_MISSING_VALUE_MAPPER = JsonMapper.builder()
            .enable(DeserializationFeature.FAIL_ON_MISSING_EXTERNAL_TYPE_ID_PROPERTY)
            .build();

    // Unknown-property failures disabled so that view filtering behavior is
    // observed directly instead of being masked by unrecognized-field errors.
    private static final JsonMapper VIEW_MAPPER = JsonMapper.builder()
            .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
            .build();

    /*
    /**********************************************************************
    /* Helper types
    /**********************************************************************
     */

    public static class ViewA { }

    public static class ViewB extends ViewA { }

    @JsonSubTypes({
        @JsonSubTypes.Type(value = PayloadA.class, name = "A"),
        @JsonSubTypes.Type(value = PayloadB.class, name = "B")
    })
    public static class Payload { }

    @JsonTypeName("A")
    public static class PayloadA extends Payload {
        public int a;
    }

    @JsonTypeName("B")
    public static class PayloadB extends Payload {
        public int b;
    }

    public static class SimpleBean {
        public final String name;
        public final Payload value;

        @JsonCreator
        public SimpleBean(@JsonProperty("name") String name,
                @JsonProperty("value")
                @JsonTypeInfo(use = JsonTypeInfo.Id.NAME, include = JsonTypeInfo.As.EXTERNAL_PROPERTY, property = "type")
                @JsonSubTypes({
                    @JsonSubTypes.Type(value = PayloadA.class, name = "A"),
                    @JsonSubTypes.Type(value = PayloadB.class, name = "B")
                })
                Payload value) {
            this.name = name;
            this.value = value;
        }
    }

    // [databind#999]: the external type id itself is also a creator property
    public static class TypedBean {
        public final String type;
        public final Payload value;

        @JsonCreator
        public TypedBean(@JsonProperty("type") String type,
                @JsonProperty("value")
                @JsonTypeInfo(use = JsonTypeInfo.Id.NAME, include = JsonTypeInfo.As.EXTERNAL_PROPERTY, property = "type")
                @JsonSubTypes({
                    @JsonSubTypes.Type(value = PayloadA.class, name = "A"),
                    @JsonSubTypes.Type(value = PayloadB.class, name = "B")
                })
                Payload value) {
            this.type = type;
            this.value = value;
        }
    }

    // [databind#1328]: creator property for the type id that is not a plain String
    public static class TypedIdObjectBean {
        public final Object type;
        public final Payload value;

        @JsonCreator
        public TypedIdObjectBean(@JsonProperty("type") Object type,
                @JsonProperty("value")
                @JsonTypeInfo(use = JsonTypeInfo.Id.NAME, include = JsonTypeInfo.As.EXTERNAL_PROPERTY, property = "type")
                @JsonSubTypes({
                    @JsonSubTypes.Type(value = PayloadA.class, name = "A"),
                    @JsonSubTypes.Type(value = PayloadB.class, name = "B")
                })
                Payload value) {
            this.type = type;
            this.value = value;
        }
    }

    // External type id property that is NOT a creator property
    public static class MixedBean {
        public final String name;

        @JsonTypeInfo(use = JsonTypeInfo.Id.NAME, include = JsonTypeInfo.As.EXTERNAL_PROPERTY, property = "type")
        @JsonSubTypes({
            @JsonSubTypes.Type(value = PayloadA.class, name = "A"),
            @JsonSubTypes.Type(value = PayloadB.class, name = "B")
        })
        public Payload value;

        @JsonCreator
        public MixedBean(@JsonProperty("name") String name) {
            this.name = name;
        }
    }

    // [databind#3786]: natural scalar values may omit the external type id
    public static class NaturalBean {
        public final String name;
        public final Object value;

        @JsonCreator
        public NaturalBean(@JsonProperty("name") String name,
                @JsonProperty("value")
                @JsonTypeInfo(use = JsonTypeInfo.Id.NAME, include = JsonTypeInfo.As.EXTERNAL_PROPERTY, property = "type")
                @JsonSubTypes({
                    @JsonSubTypes.Type(value = PayloadA.class, name = "A"),
                    @JsonSubTypes.Type(value = PayloadB.class, name = "B")
                })
                Object value) {
            this.name = name;
            this.value = value;
        }
    }

    // [databind#94]: defaultImpl used when external type id is missing
    public static class DefaultImplBean {
        public final String name;
        public final Payload value;

        @JsonCreator
        public DefaultImplBean(@JsonProperty("name") String name,
                @JsonProperty("value")
                @JsonTypeInfo(use = JsonTypeInfo.Id.NAME, include = JsonTypeInfo.As.EXTERNAL_PROPERTY, property = "type",
                        defaultImpl = PayloadA.class)
                @JsonSubTypes({
                    @JsonSubTypes.Type(value = PayloadA.class, name = "A"),
                    @JsonSubTypes.Type(value = PayloadB.class, name = "B")
                })
                Payload value) {
            this.name = name;
            this.value = value;
        }
    }

    // [databind#6055]: external type id property filtered by the active JsonView
    public static class ViewedBean {
        public final String name;
        public final Payload value;

        @JsonCreator
        public ViewedBean(@JsonProperty("name") String name,
                @JsonProperty("value")
                @JsonView(ViewB.class)
                @JsonTypeInfo(use = JsonTypeInfo.Id.NAME, include = JsonTypeInfo.As.EXTERNAL_PROPERTY, property = "type")
                @JsonSubTypes({
                    @JsonSubTypes.Type(value = PayloadA.class, name = "A"),
                    @JsonSubTypes.Type(value = PayloadB.class, name = "B")
                })
                Payload value) {
            this.name = name;
            this.value = value;
        }
    }

    /*
    /**********************************************************************
    /* Tests: basic external type id handling
    /**********************************************************************
     */

    @Test
    public void testExternalTypeIdWithCreatorPropertyTypeFirst() {
        SimpleBean bean = MAPPER.readValue("{\"name\":\"Bob\",\"type\":\"A\",\"value\":{\"a\":3}}",
                SimpleBean.class);
        assertEquals("Bob", bean.name);
        assertTrue(bean.value instanceof PayloadA);
        assertEquals(3, ((PayloadA) bean.value).a);
    }

    @Test
    public void testExternalTypeIdWithCreatorPropertyTypeLast() {
        SimpleBean bean = MAPPER.readValue("{\"value\":{\"b\":4},\"type\":\"B\",\"name\":\"Sam\"}",
                SimpleBean.class);
        assertEquals("Sam", bean.name);
        assertTrue(bean.value instanceof PayloadB);
        assertEquals(4, ((PayloadB) bean.value).b);
    }

    @Test
    public void testExternalTypeIdAsCreatorProperty() {
        TypedBean bean = MAPPER.readValue("{\"type\":\"A\",\"value\":{\"a\":5}}", TypedBean.class);
        assertEquals("A", bean.type);
        assertTrue(bean.value instanceof PayloadA);
        assertEquals(5, ((PayloadA) bean.value).a);
    }

    @Test
    public void testExternalTypeIdAsNonStringCreatorProperty() {
        TypedIdObjectBean bean = MAPPER.readValue("{\"type\":\"B\",\"value\":{\"b\":6}}",
                TypedIdObjectBean.class);
        assertEquals("B", bean.type);
        assertTrue(bean.value instanceof PayloadB);
        assertEquals(6, ((PayloadB) bean.value).b);
    }

    @Test
    public void testExternalTypeIdWithNonCreatorProperty() {
        MixedBean bean = MAPPER.readValue("{\"name\":\"n\",\"type\":\"A\",\"value\":{\"a\":2}}", MixedBean.class);
        assertEquals("n", bean.name);
        assertTrue(bean.value instanceof PayloadA);
        assertEquals(2, ((PayloadA) bean.value).a);
    }

    /*
    /**********************************************************************
    /* Tests: missing type ids, defaults, natural scalars, nulls
    /**********************************************************************
     */

    @Test
    public void testMissingExternalTypeIdFails() {
        try {
            MAPPER.readValue("{\"name\":\"n\",\"value\":{\"a\":1}}", SimpleBean.class);
            fail("Should not accept a payload value without the external type id");
        } catch (JacksonException e) {
            verifyException(e, "missing external type id");
        }
    }

    @Test
    public void testDefaultImplUsedWhenExternalTypeIdMissing() {
        DefaultImplBean bean = MAPPER.readValue("{\"name\":\"n\",\"value\":{\"a\":1}}", DefaultImplBean.class);
        assertEquals("n", bean.name);
        assertTrue(bean.value instanceof PayloadA);
        assertEquals(1, ((PayloadA) bean.value).a);
    }

    @Test
    public void testNaturalScalarStringWithoutExternalTypeId() {
        NaturalBean bean = MAPPER.readValue("{\"name\":\"n\",\"value\":\"text\"}", NaturalBean.class);
        assertEquals("n", bean.name);
        assertEquals("text", bean.value);
    }

    @Test
    public void testNaturalScalarNumberWithoutExternalTypeId() {
        NaturalBean bean = MAPPER.readValue("{\"name\":\"n\",\"value\":42}", NaturalBean.class);
        assertEquals("n", bean.name);
        assertEquals(42, ((Number) bean.value).intValue());
    }

    @Test
    public void testExplicitNullValueWithoutExternalTypeId() {
        SimpleBean bean = MAPPER.readValue("{\"name\":\"n\",\"value\":null}", SimpleBean.class);
        assertEquals("n", bean.name);
        assertNull(bean.value);
    }

    @Test
    public void testMissingValueAndTypeIdSkipped() {
        SimpleBean bean = MAPPER.readValue("{\"name\":\"n\"}", SimpleBean.class);
        assertEquals("n", bean.name);
        assertNull(bean.value);
    }

    @Test
    public void testPresentTypeIdMissingValueFailsWhenFeatureEnabled() {
        try {
            STRICT_MISSING_VALUE_MAPPER.readValue("{\"name\":\"n\",\"type\":\"A\"}", SimpleBean.class);
            fail("Should have failed when value property is missing but type id is present");
        } catch (JacksonException e) {
            verifyException(e, "missing property");
        }
    }

    /*
    /**********************************************************************
    /* Tests: active view filtering ([databind#6055])
    /**********************************************************************
     */

    @Test
    public void testViewFilteredExternalTypeIdSkipsValue() {
        ViewedBean bean = VIEW_MAPPER.readerFor(ViewedBean.class)
                .withView(ViewA.class)
                .readValue("{\"name\":\"n\",\"type\":\"A\",\"value\":{\"a\":7}}");
        assertEquals("n", bean.name);
        assertNull(bean.value);
    }

    @Test
    public void testViewFilteredExternalTypeIdWithoutTypeIdDoesNotFail() {
        ViewedBean bean = VIEW_MAPPER.readerFor(ViewedBean.class)
                .withView(ViewA.class)
                .readValue("{\"name\":\"n\",\"value\":{\"a\":7}}");
        assertEquals("n", bean.name);
        assertNull(bean.value);
    }

    @Test
    public void testViewIncludedExternalTypeIdDeserialized() {
        ViewedBean bean = VIEW_MAPPER.readerFor(ViewedBean.class)
                .withView(ViewB.class)
                .readValue("{\"name\":\"n\",\"type\":\"A\",\"value\":{\"a\":7}}");
        assertEquals("n", bean.name);
        assertTrue(bean.value instanceof PayloadA);
        assertEquals(7, ((PayloadA) bean.value).a);
    }

    private static void verifyException(Throwable e, String... matches) {
        String msg = e.getMessage();
        String lmsg = (msg == null) ? "" : msg.toLowerCase();
        for (String match : matches) {
            if (!lmsg.contains(match.toLowerCase())) {
                fail("Expected an exception message containing \"" + match
                        + "\" but message was: " + msg);
            }
        }
    }
}