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

// Tests for ExternalTypeHandler.complete(...) when the target bean is built
// with a property-based creator and properties use external type ids.
public class CompleteTests
{
    private static final ObjectMapper MAPPER = JsonMapper.builder().build();

    public interface ViewFull { }

    public interface ViewRestricted { }

    public interface ExtValue { }

    public static class ExtValueImpl implements ExtValue
    {
        public int x;

        public ExtValueImpl() { }

        public ExtValueImpl(int x) { this.x = x; }
    }

    public enum KindEnum { IMPL }

    // External type id on a creator property, with the type id itself also
    // exposed as a String creator property.
    public static class CreatorBean
    {
        public int a;
        public ExtValue value;
        public String capturedType;

        @JsonCreator
        public CreatorBean(@JsonProperty("a") int a,
                @JsonProperty("value")
                @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                        include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                        property = "extType")
                @JsonSubTypes(@JsonSubTypes.Type(value = ExtValueImpl.class, name = "impl"))
                ExtValue value,
                @JsonProperty("extType") String capturedType)
        {
            this.a = a;
            this.value = value;
            this.capturedType = capturedType;
        }
    }

    // External type id on a plain (non-creator) property of a creator-based bean.
    public static class MixedBean
    {
        public int a;

        @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                property = "type")
        @JsonSubTypes(@JsonSubTypes.Type(value = ExtValueImpl.class, name = "impl"))
        public ExtValue value;

        @JsonCreator
        public MixedBean(@JsonProperty("a") int a)
        {
            this.a = a;
        }
    }

    // External type id with Id.CLASS and a scalar-tolerant Object property.
    public static class NaturalBean
    {
        public int a;
        public Object data;

        @JsonCreator
        public NaturalBean(@JsonProperty("a") int a,
                @JsonProperty("data")
                @JsonTypeInfo(use = JsonTypeInfo.Id.CLASS,
                        include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                        property = "kind")
                Object data)
        {
            this.a = a;
            this.data = data;
        }
    }

    // External type id with a default implementation for missing type ids.
    public static class DefaultImplBean
    {
        public int a;
        public ExtValue value;

        @JsonCreator
        public DefaultImplBean(@JsonProperty("a") int a,
                @JsonProperty("value")
                @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                        include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                        property = "type",
                        defaultImpl = ExtValueImpl.class)
                @JsonSubTypes(@JsonSubTypes.Type(value = ExtValueImpl.class, name = "impl"))
                ExtValue value)
        {
            this.a = a;
            this.value = value;
        }
    }

    // External type id where the type id creator property is not a String.
    public static class EnumTypeBean
    {
        public int a;
        public ExtValue value;
        public KindEnum kind;

        @JsonCreator
        public EnumTypeBean(@JsonProperty("a") int a,
                @JsonProperty("value")
                @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                        include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                        property = "kind")
                @JsonSubTypes(@JsonSubTypes.Type(value = ExtValueImpl.class, name = "IMPL"))
                ExtValue value,
                @JsonProperty("kind") KindEnum kind)
        {
            this.a = a;
            this.value = value;
            this.kind = kind;
        }
    }

    // External type id property limited to ViewFull via @JsonView.
    public static class ViewedBean
    {
        public int a;
        public ExtValue value;

        @JsonCreator
        public ViewedBean(@JsonProperty("a")
                @JsonView({ ViewFull.class, ViewRestricted.class }) int a,
                @JsonProperty("value") @JsonView(ViewFull.class)
                @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                        include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                        property = "type")
                @JsonSubTypes(@JsonSubTypes.Type(value = ExtValueImpl.class, name = "impl"))
                ExtValue value)
        {
            this.a = a;
            this.value = value;
        }
    }

    private static void verifyMessageContains(JacksonException e, String expectedPart)
    {
        String msg = e.getMessage();
        assertNotNull("Exception should have a message, got null", msg);
        assertTrue("Expected message to contain <" + expectedPart + ">, was: <" + msg + ">",
                msg.contains(expectedPart));
    }

    @Test
    public void testCreatorExternalTypeIdBasic() throws Exception
    {
        CreatorBean bean = MAPPER.readValue(
                "{\"a\":2,\"extType\":\"impl\",\"value\":{\"x\":7}}", CreatorBean.class);
        assertEquals(2, bean.a);
        assertNotNull(bean.value);
        assertTrue(bean.value instanceof ExtValueImpl);
        assertEquals(7, ((ExtValueImpl) bean.value).x);
        assertEquals("impl", bean.capturedType);
    }

    @Test
    public void testCreatorExternalTypeIdReversedPropertyOrder() throws Exception
    {
        CreatorBean bean = MAPPER.readValue(
                "{\"value\":{\"x\":8},\"extType\":\"impl\",\"a\":3}", CreatorBean.class);
        assertEquals(3, bean.a);
        assertEquals(8, ((ExtValueImpl) bean.value).x);
        assertEquals("impl", bean.capturedType);
    }

    @Test
    public void testNonCreatorExternalTypePropertyWithCreatorBean() throws Exception
    {
        MixedBean bean = MAPPER.readValue(
                "{\"a\":5,\"type\":\"impl\",\"value\":{\"x\":11}}", MixedBean.class);
        assertEquals(5, bean.a);
        assertTrue(bean.value instanceof ExtValueImpl);
        assertEquals(11, ((ExtValueImpl) bean.value).x);
    }

    @Test
    public void testMissingExternalTypeIdReported() throws Exception
    {
        try {
            MAPPER.readValue("{\"a\":1,\"value\":{\"x\":3}}", CreatorBean.class);
            fail("Should not accept missing external type id without defaultImpl");
        } catch (JacksonException e) {
            verifyMessageContains(e, "Missing external type id property");
        }
    }

    @Test
    public void testExplicitNullValueWithoutTypeIdSkipped() throws Exception
    {
        CreatorBean bean = MAPPER.readValue("{\"a\":1,\"value\":null}", CreatorBean.class);
        assertEquals(1, bean.a);
        assertNull(bean.value);
        assertNull(bean.capturedType);
    }

    @Test
    public void testNaturalScalarValueWithoutTypeId() throws Exception
    {
        NaturalBean bean = MAPPER.readValue("{\"a\":3,\"data\":\"abc\"}", NaturalBean.class);
        assertEquals(3, bean.a);
        assertEquals("abc", bean.data);
    }

    @Test
    public void testDefaultImplUsedWhenTypeIdMissing() throws Exception
    {
        DefaultImplBean bean = MAPPER.readValue(
                "{\"a\":4,\"value\":{\"x\":9}}", DefaultImplBean.class);
        assertEquals(4, bean.a);
        assertTrue(bean.value instanceof ExtValueImpl);
        assertEquals(9, ((ExtValueImpl) bean.value).x);
    }

    @Test
    public void testMissingValueWithTypeIdPresentBuildsEmptyInstance() throws Exception
    {
        MixedBean bean = MAPPER.readValue("{\"a\":6,\"type\":\"impl\"}", MixedBean.class);
        assertEquals(6, bean.a);
        assertNotNull(bean.value);
        assertTrue(bean.value instanceof ExtValueImpl);
        assertEquals(0, ((ExtValueImpl) bean.value).x);
    }

    @Test
    public void testMissingValueWithTypeIdPresentFailsIfFeatureEnabled() throws Exception
    {
        ObjectMapper strictMapper = JsonMapper.builder()
                .enable(DeserializationFeature.FAIL_ON_MISSING_EXTERNAL_TYPE_ID_PROPERTY)
                .build();
        try {
            strictMapper.readValue("{\"a\":6,\"type\":\"impl\"}", MixedBean.class);
            fail("Should not pass when FAIL_ON_MISSING_EXTERNAL_TYPE_ID_PROPERTY is enabled");
        } catch (JacksonException e) {
            verifyMessageContains(e, "Missing property");
        }
    }

    @Test
    public void testNonStringCreatorTypeIdProperty() throws Exception
    {
        EnumTypeBean bean = MAPPER.readValue(
                "{\"a\":9,\"kind\":\"IMPL\",\"value\":{\"x\":13}}", EnumTypeBean.class);
        assertEquals(9, bean.a);
        assertEquals(KindEnum.IMPL, bean.kind);
        assertTrue(bean.value instanceof ExtValueImpl);
        assertEquals(13, ((ExtValueImpl) bean.value).x);
    }

    @Test
    public void testViewFilteredExternalTypePropertySkipped() throws Exception
    {
        // Property not part of ViewRestricted; the missing type id must be
        // skipped rather than reported as an input mismatch.
        ViewedBean bean = MAPPER.readerFor(ViewedBean.class)
                .withView(ViewRestricted.class)
                .readValue("{\"a\":1}");
        assertEquals(1, bean.a);
        assertNull(bean.value);
    }

    @Test
    public void testViewFilteredExternalTypePropertyIgnoresBufferedValue() throws Exception
    {
        // Property filtered by the view must not bind the buffered value.
        ViewedBean bean = MAPPER.readerFor(ViewedBean.class)
                .withView(ViewRestricted.class)
                .readValue("{\"a\":1,\"type\":\"impl\",\"value\":{\"x\":5}}");
        assertEquals(1, bean.a);
        assertNull(bean.value);
    }

    @Test
    public void testViewIncludedExternalTypePropertyDeserialized() throws Exception
    {
        ViewedBean bean = MAPPER.readerFor(ViewedBean.class)
                .withView(ViewFull.class)
                .readValue("{\"a\":1,\"type\":\"impl\",\"value\":{\"x\":5}}");
        assertEquals(1, bean.a);
        assertTrue(bean.value instanceof ExtValueImpl);
        assertEquals(5, ((ExtValueImpl) bean.value).x);

        ViewedBean bean2 = MAPPER.readValue(
                "{\"a\":2,\"type\":\"impl\",\"value\":{\"x\":6}}", ViewedBean.class);
        assertEquals(2, bean2.a);
        assertEquals(6, ((ExtValueImpl) bean2.value).x);
    }
}