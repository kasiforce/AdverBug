package tools.jackson.databind.deser.impl;

import org.junit.Test;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.annotation.JsonSubTypes;
import com.fasterxml.jackson.annotation.JsonTypeInfo;
import com.fasterxml.jackson.annotation.JsonView;

import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.exc.MismatchedInputException;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

/**
 * Tests for the creator-based completion step of external type id handling
 * ({@code ExternalTypeHandler.complete(JsonParser, DeserializationContext,
 * PropertyValueBuffer, PropertyBasedCreator)}), exercised end-to-end through
 * the public {@link JsonMapper} API.
 *
 * Covered behaviors:
 * <ul>
 * <li>Basic external type id binding for creator and non-creator properties</li>
 * <li>Natural (scalar) values with missing type ids</li>
 * <li>Explicit null values with missing type ids</li>
 * <li>Missing both type id and value</li>
 * <li>defaultImpl fallback when type id is missing</li>
 * <li>Missing value with present type id, with and without
 *     FAIL_ON_MISSING_EXTERNAL_TYPE_ID_PROPERTY</li>
 * <li>Active JsonView filtering of external type id properties</li>
 * <li>Non-String creator properties bound to the type id itself</li>
 * </ul>
 */
public class CompleteTests
{
    /*
    /**********************************************************************
    /* Helper types
    /**********************************************************************
     */

    public static class IntWrapper {
        public int x;

        public IntWrapper() { }

        public IntWrapper(int x) { this.x = x; }
    }

    public static class StringWrapper {
        public String s;

        public StringWrapper() { }

        public StringWrapper(String s) { this.s = s; }
    }

    public static class Views {
        public static class A { }
        public static class B { }
    }

    public enum TypeId { intw, strw }

    public static class SimpleCreatorBean {
        final String name;
        final String type;
        final Object value;

        @JsonCreator
        public SimpleCreatorBean(
                @JsonProperty("name") String name,
                @JsonProperty("type") String type,
                @JsonProperty("value")
                @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                        include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                        property = "type")
                @JsonSubTypes({
                        @JsonSubTypes.Type(value = IntWrapper.class, name = "intw"),
                        @JsonSubTypes.Type(value = StringWrapper.class, name = "strw")
                })
                Object value)
        {
            this.name = name;
            this.type = type;
            this.value = value;
        }
    }

    public static class DefaultImplCreatorBean {
        final Object value;

        @JsonCreator
        public DefaultImplCreatorBean(
                @JsonProperty("value")
                @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                        include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                        property = "type",
                        defaultImpl = IntWrapper.class)
                @JsonSubTypes({
                        @JsonSubTypes.Type(value = IntWrapper.class, name = "intw")
                })
                Object value)
        {
            this.value = value;
        }
    }

    public static class ViewCreatorBean {
        final String type;
        final Object value;

        @JsonCreator
        public ViewCreatorBean(
                @JsonProperty("type") String type,
                @JsonProperty("value")
                @JsonView(Views.A.class)
                @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                        include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                        property = "type")
                @JsonSubTypes({
                        @JsonSubTypes.Type(value = IntWrapper.class, name = "intw")
                })
                Object value)
        {
            this.type = type;
            this.value = value;
        }
    }

    public static class NonCreatorValueBean {
        public String name;

        @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                property = "type")
        @JsonSubTypes({
                @JsonSubTypes.Type(value = IntWrapper.class, name = "intw")
        })
        public Object value;

        @JsonCreator
        public NonCreatorValueBean(@JsonProperty("name") String name) {
            this.name = name;
        }
    }

    public static class EnumTypeIdCreatorBean {
        final TypeId type;
        final Object value;

        @JsonCreator
        public EnumTypeIdCreatorBean(
                @JsonProperty("type") TypeId type,
                @JsonProperty("value")
                @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                        include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                        property = "type")
                @JsonSubTypes({
                        @JsonSubTypes.Type(value = IntWrapper.class, name = "intw"),
                        @JsonSubTypes.Type(value = StringWrapper.class, name = "strw")
                })
                Object value)
        {
            this.type = type;
            this.value = value;
        }
    }

    /*
    /**********************************************************************
    /* Tests
    /**********************************************************************
     */

    @Test
    public void testExternalTypeIdWithCreatorProperty() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        SimpleCreatorBean bean = mapper.readValue(
                "{\"name\":\"bob\",\"type\":\"intw\",\"value\":{\"x\":42}}",
                SimpleCreatorBean.class);
        assertEquals("bob", bean.name);
        assertEquals("intw", bean.type);
        assertTrue("Expected IntWrapper, got: " + bean.value,
                bean.value instanceof IntWrapper);
        assertEquals(42, ((IntWrapper) bean.value).x);
    }

    @Test
    public void testExternalTypeIdWithCreatorPropertyStringSubtype() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        SimpleCreatorBean bean = mapper.readValue(
                "{\"name\":\"sam\",\"type\":\"strw\",\"value\":{\"s\":\"hello\"}}",
                SimpleCreatorBean.class);
        assertTrue("Expected StringWrapper, got: " + bean.value,
                bean.value instanceof StringWrapper);
        assertEquals("hello", ((StringWrapper) bean.value).s);
        assertEquals("strw", bean.type);
    }

    @Test
    public void testNaturalStringValueWithoutTypeId() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        SimpleCreatorBean bean = mapper.readValue(
                "{\"name\":\"nat\",\"value\":\"plain\"}",
                SimpleCreatorBean.class);
        assertEquals("plain", bean.value);
        assertNull(bean.type);
    }

    @Test
    public void testNaturalNumberValueWithoutTypeId() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        SimpleCreatorBean bean = mapper.readValue(
                "{\"name\":\"num\",\"value\":42}",
                SimpleCreatorBean.class);
        assertTrue("Expected natural number value, got: " + bean.value,
                bean.value instanceof Number);
        assertEquals(42, ((Number) bean.value).intValue());
    }

    @Test
    public void testExplicitNullValueWithoutTypeIdIsAccepted() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        SimpleCreatorBean bean = mapper.readValue(
                "{\"name\":\"nul\",\"value\":null}",
                SimpleCreatorBean.class);
        assertNull(bean.value);
        assertNull(bean.type);
    }

    @Test
    public void testMissingBothTypeIdAndValueIsAccepted() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        SimpleCreatorBean bean = mapper.readValue(
                "{\"name\":\"none\"}",
                SimpleCreatorBean.class);
        assertNull(bean.value);
        assertNull(bean.type);
    }

    @Test
    public void testMissingTypeIdForStructuredValueFails() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        try {
            mapper.readValue(
                    "{\"name\":\"pojo\",\"value\":{\"x\":1}}",
                    SimpleCreatorBean.class);
            fail("Expected MismatchedInputException for missing external type id");
        } catch (MismatchedInputException e) {
            // expected: no defaultImpl registered
        }
    }

    @Test
    public void testDefaultImplUsedWhenTypeIdMissing() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        DefaultImplCreatorBean bean = mapper.readValue(
                "{\"value\":{\"x\":7}}",
                DefaultImplCreatorBean.class);
        assertTrue("Expected IntWrapper from defaultImpl, got: " + bean.value,
                bean.value instanceof IntWrapper);
        assertEquals(7, ((IntWrapper) bean.value).x);
    }

    @Test
    public void testMissingValueWithTypeIdAllowedWhenFeatureDisabled() throws Exception {
        JsonMapper mapper = JsonMapper.builder()
                .disable(DeserializationFeature.FAIL_ON_MISSING_EXTERNAL_TYPE_ID_PROPERTY)
                .build();
        SimpleCreatorBean bean = mapper.readValue(
                "{\"name\":\"ot\",\"type\":\"intw\"}",
                SimpleCreatorBean.class);
        assertEquals("intw", bean.type);
    }

    @Test
    public void testMissingValueWithTypeIdFailsWhenFeatureEnabled() throws Exception {
        JsonMapper mapper = JsonMapper.builder()
                .enable(DeserializationFeature.FAIL_ON_MISSING_EXTERNAL_TYPE_ID_PROPERTY)
                .build();
        try {
            mapper.readValue(
                    "{\"name\":\"ot\",\"type\":\"intw\"}",
                    SimpleCreatorBean.class);
            fail("Expected MismatchedInputException when value missing with feature enabled");
        } catch (MismatchedInputException e) {
            // expected
        }
    }

    @Test
    public void testViewFilteredExternalTypePropertyIsSkipped() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        ViewCreatorBean bean = mapper.readerFor(ViewCreatorBean.class)
                .withView(Views.B.class)
                .readValue("{\"type\":\"intw\",\"value\":{\"x\":1}}");
        assertNull(bean.value);
    }

    @Test
    public void testViewIncludedExternalTypePropertyIsDeserialized() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        ViewCreatorBean bean = mapper.readerFor(ViewCreatorBean.class)
                .withView(Views.A.class)
                .readValue("{\"type\":\"intw\",\"value\":{\"x\":1}}");
        assertTrue("Expected IntWrapper, got: " + bean.value,
                bean.value instanceof IntWrapper);
        assertEquals(1, ((IntWrapper) bean.value).x);
    }

    @Test
    public void testNonCreatorExternalTypePropertyAssignedToBean() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        NonCreatorValueBean bean = mapper.readValue(
                "{\"name\":\"mixed\",\"type\":\"intw\",\"value\":{\"x\":9}}",
                NonCreatorValueBean.class);
        assertEquals("mixed", bean.name);
        assertTrue("Expected IntWrapper, got: " + bean.value,
                bean.value instanceof IntWrapper);
        assertEquals(9, ((IntWrapper) bean.value).x);
    }

    @Test
    public void testNaturalStringValueWithoutTypeIdNonCreatorProperty() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        NonCreatorValueBean bean = mapper.readValue(
                "{\"name\":\"nat2\",\"value\":\"plain\"}",
                NonCreatorValueBean.class);
        assertEquals("plain", bean.value);
    }

    @Test
    public void testNonStringCreatorPropertyForTypeId() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        EnumTypeIdCreatorBean bean = mapper.readValue(
                "{\"type\":\"intw\",\"value\":{\"x\":3}}",
                EnumTypeIdCreatorBean.class);
        assertSame(TypeId.intw, bean.type);
        assertTrue("Expected IntWrapper, got: " + bean.value,
                bean.value instanceof IntWrapper);
        assertEquals(3, ((IntWrapper) bean.value).x);
    }
}