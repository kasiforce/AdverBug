package tools.jackson.databind.deser.impl;

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

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

/**
 * Tests for {@code ExternalTypeHandler.complete(JsonParser, DeserializationContext,
 * PropertyValueBuffer, PropertyBasedCreator)}, exercised end-to-end through
 * creator-based deserialization of beans whose properties use external type ids
 * ({@code @JsonTypeInfo(include = As.EXTERNAL_PROPERTY)}).
 */
public class CompleteTests
{
    // ------------------------------------------------------------------
    // Payload types used with external type ids
    // ------------------------------------------------------------------

    public static class Square {
        public int size;
    }

    public static class Circle {
        public int radius;
    }

    public static class DefaultShapePayload {
        public String label;
    }

    public static class Views {
        public static class Public { }
        public static class Internal extends Public { }
    }

    // ------------------------------------------------------------------
    // Beans under test
    // ------------------------------------------------------------------

    /** Externally-typed value bound through a creator parameter. */
    public static class CreatorExternalBean {
        final Object _shape;

        @JsonCreator
        public CreatorExternalBean(
                @JsonProperty("shape")
                @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                        include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                        property = "shapeType")
                @JsonSubTypes({
                    @JsonSubTypes.Type(value = Square.class, name = "square"),
                    @JsonSubTypes.Type(value = Circle.class, name = "circle")
                })
                Object shape) {
            _shape = shape;
        }

        public Object getShape() { return _shape; }
    }

    /** The external type id itself is a String creator property (databind#999). */
    public static class CreatorWithTypeIdBean {
        final Object _shape;
        final String _shapeType;

        @JsonCreator
        public CreatorWithTypeIdBean(
                @JsonProperty("shape")
                @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                        include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                        property = "shapeType")
                @JsonSubTypes({
                    @JsonSubTypes.Type(value = Square.class, name = "square"),
                    @JsonSubTypes.Type(value = Circle.class, name = "circle")
                })
                Object shape,
                @JsonProperty("shapeType") String shapeType) {
            _shape = shape;
            _shapeType = shapeType;
        }

        public Object getShape() { return _shape; }
        public String getShapeType() { return _shapeType; }
    }

    /** The external type id is a non-String (int) creator property (databind#1328). */
    public static class CreatorWithIntTypeIdBean {
        final Object _shape;
        final int _shapeType;

        @JsonCreator
        public CreatorWithIntTypeIdBean(
                @JsonProperty("shape")
                @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                        include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                        property = "shapeType")
                @JsonSubTypes({
                    @JsonSubTypes.Type(value = Square.class, name = "1"),
                    @JsonSubTypes.Type(value = Circle.class, name = "2")
                })
                Object shape,
                @JsonProperty("shapeType") int shapeType) {
            _shape = shape;
            _shapeType = shapeType;
        }

        public Object getShape() { return _shape; }
        public int getShapeType() { return _shapeType; }
    }

    /** Creator supplies one property; the externally-typed property is a plain field. */
    public static class MixedCreatorBean {
        public final String id;

        @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                property = "shapeType")
        @JsonSubTypes({
            @JsonSubTypes.Type(value = Square.class, name = "square"),
            @JsonSubTypes.Type(value = Circle.class, name = "circle")
        })
        public Object shape;

        @JsonCreator
        public MixedCreatorBean(@JsonProperty("id") String id) {
            this.id = id;
        }
    }

    /** No type id given; scalar value should bind "naturally" (databind#3786). */
    public static class NaturalScalarBean {
        final Object _value;

        @JsonCreator
        public NaturalScalarBean(
                @JsonProperty("value")
                @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                        include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                        property = "valueType")
                Object value) {
            _value = value;
        }

        public Object getValue() { return _value; }
    }

    /** Missing type id falls back to the configured default implementation. */
    public static class DefaultImplBean {
        final Object _shape;

        @JsonCreator
        public DefaultImplBean(
                @JsonProperty("shape")
                @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                        include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                        property = "shapeType",
                        defaultImpl = DefaultShapePayload.class)
                Object shape) {
            _shape = shape;
        }

        public Object getShape() { return _shape; }
    }

    /** External property may be excluded by the active JsonView (databind#6055). */
    public static class ViewScopedBean {
        final Object _shape;

        @JsonCreator
        public ViewScopedBean(
                @JsonProperty("shape")
                @JsonView(Views.Internal.class)
                @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                        include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                        property = "shapeType")
                @JsonSubTypes({
                    @JsonSubTypes.Type(value = Square.class, name = "square"),
                    @JsonSubTypes.Type(value = Circle.class, name = "circle")
                })
                Object shape) {
            _shape = shape;
        }

        public Object getShape() { return _shape; }
    }

    // ------------------------------------------------------------------
    // Mappers
    // ------------------------------------------------------------------

    private final ObjectMapper MAPPER = JsonMapper.builder().build();

    private final ObjectMapper STRICT_MAPPER = JsonMapper.builder()
            .enable(DeserializationFeature.FAIL_ON_MISSING_EXTERNAL_TYPE_ID_PROPERTY)
            .build();

    private final ObjectMapper LENIENT_MAPPER = JsonMapper.builder()
            .disable(DeserializationFeature.FAIL_ON_MISSING_EXTERNAL_TYPE_ID_PROPERTY)
            .build();

    // ------------------------------------------------------------------
    // Tests: basic functionality
    // ------------------------------------------------------------------

    @Test
    public void testCreatorExternalTypeIdResolvesSubtypeSquare() {
        CreatorExternalBean bean = MAPPER.readValue(
                "{\"shapeType\":\"square\",\"shape\":{\"size\":3}}",
                CreatorExternalBean.class);
        assertTrue(bean.getShape() instanceof Square);
        assertEquals(3, ((Square) bean.getShape()).size);
    }

    @Test
    public void testCreatorExternalTypeIdResolvesSubtypeCircle() {
        CreatorExternalBean bean = MAPPER.readValue(
                "{\"shapeType\":\"circle\",\"shape\":{\"radius\":7}}",
                CreatorExternalBean.class);
        assertTrue(bean.getShape() instanceof Circle);
        assertEquals(7, ((Circle) bean.getShape()).radius);
    }

    @Test
    public void testCreatorTypeIdExposedAsStringProperty() {
        CreatorWithTypeIdBean bean = MAPPER.readValue(
                "{\"shapeType\":\"circle\",\"shape\":{\"radius\":4}}",
                CreatorWithTypeIdBean.class);
        assertEquals("circle", bean.getShapeType());
        assertTrue(bean.getShape() instanceof Circle);
        assertEquals(4, ((Circle) bean.getShape()).radius);
    }

    @Test
    public void testCreatorTypeIdDeserializedForNonStringProperty() {
        CreatorWithIntTypeIdBean bean = MAPPER.readValue(
                "{\"shapeType\":\"1\",\"shape\":{\"size\":5}}",
                CreatorWithIntTypeIdBean.class);
        assertEquals(1, bean.getShapeType());
        assertTrue(bean.getShape() instanceof Square);
        assertEquals(5, ((Square) bean.getShape()).size);
    }

    @Test
    public void testNonCreatorExternalPropertyAssignedAfterCreatorBuild() {
        MixedCreatorBean bean = MAPPER.readValue(
                "{\"id\":\"abc\",\"shapeType\":\"square\",\"shape\":{\"size\":6}}",
                MixedCreatorBean.class);
        assertEquals("abc", bean.id);
        assertTrue(bean.shape instanceof Square);
        assertEquals(6, ((Square) bean.shape).size);
    }

    // ------------------------------------------------------------------
    // Tests: boundary conditions and special handling paths
    // ------------------------------------------------------------------

    @Test
    public void testNaturalScalarWithoutTypeIdBoundAsNaturalValue() {
        NaturalScalarBean bean = MAPPER.readValue(
                "{\"value\":\"plain\"}", NaturalScalarBean.class);
        assertEquals("plain", bean.getValue());
    }

    @Test
    public void testDefaultImplUsedWhenTypeIdMissing() {
        DefaultImplBean bean = MAPPER.readValue(
                "{\"shape\":{\"label\":\"lbl\"}}", DefaultImplBean.class);
        assertTrue(bean.getShape() instanceof DefaultShapePayload);
        assertEquals("lbl", ((DefaultShapePayload) bean.getShape()).label);
    }

    @Test
    public void testExplicitNullValueWithoutTypeIdLeavesPropertyNull() {
        CreatorExternalBean bean = MAPPER.readValue(
                "{\"shape\":null}", CreatorExternalBean.class);
        assertNull(bean.getShape());
    }

    @Test
    public void testCompletelyAbsentPropertiesLeavePropertyNull() {
        CreatorExternalBean bean = MAPPER.readValue("{}", CreatorExternalBean.class);
        assertNull(bean.getShape());
    }

    @Test
    public void testJsonViewIncludingPropertyBindsIt() {
        ViewScopedBean bean = MAPPER.readerFor(ViewScopedBean.class)
                .withView(Views.Internal.class)
                .readValue("{\"shapeType\":\"square\",\"shape\":{\"size\":2}}");
        assertTrue(bean.getShape() instanceof Square);
        assertEquals(2, ((Square) bean.getShape()).size);
    }

    @Test
    public void testJsonViewExcludingPropertySkipsIt() {
        ViewScopedBean bean = MAPPER.readerFor(ViewScopedBean.class)
                .withView(Views.Public.class)
                .readValue("{\"shapeType\":\"square\",\"shape\":{\"size\":2}}");
        assertNull(bean.getShape());
    }

    // ------------------------------------------------------------------
    // Tests: invalid inputs and error handling
    // ------------------------------------------------------------------

    @Test
    public void testMissingTypeIdWithoutDefaultImplFails() {
        try {
            MAPPER.readValue("{\"shape\":{\"size\":3}}", CreatorExternalBean.class);
            fail("Should have failed: missing external type id property");
        } catch (JacksonException e) {
            assertTrue("Unexpected message: " + e.getMessage(),
                    e.getMessage().contains("Missing external type id property"));
        }
    }

    @Test
    public void testMissingValueForPresentTypeIdFailsWhenFeatureEnabled() {
        try {
            STRICT_MAPPER.readValue("{\"shapeType\":\"square\"}", CreatorExternalBean.class);
            fail("Should have failed: missing value property for external type id");
        } catch (JacksonException e) {
            assertTrue("Unexpected message: " + e.getMessage(),
                    e.getMessage().contains("Missing property"));
        }
    }

    @Test
    public void testMissingValueForPresentTypeIdNullWhenFeatureDisabled() {
        CreatorExternalBean bean = LENIENT_MAPPER.readValue(
                "{\"shapeType\":\"square\"}", CreatorExternalBean.class);
        assertNull(bean.getShape());
    }
}