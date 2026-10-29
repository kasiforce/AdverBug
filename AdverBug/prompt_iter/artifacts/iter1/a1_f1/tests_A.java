package tools.jackson.databind.deser.jdk;

import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.fail;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.EnumMap;

import org.junit.Before;
import org.junit.Test;
import org.mockito.InOrder;

import tools.jackson.core.JsonParser;
import tools.jackson.core.JsonToken;
import tools.jackson.databind.DeserializationContext;
import tools.jackson.databind.JavaType;
import tools.jackson.databind.KeyDeserializer;
import tools.jackson.databind.ValueDeserializer;
import tools.jackson.databind.cfg.EnumFeature;
import tools.jackson.databind.deser.SettableBeanProperty;
import tools.jackson.databind.deser.ValueInstantiator;
import tools.jackson.databind.deser.bean.PropertyBasedCreator;
import tools.jackson.databind.deser.bean.PropertyValueBuffer;
import tools.jackson.databind.json.JsonMapper;

/**
 * White-box unit tests for {@link EnumMapDeserializer#_deserializeUsingProperties(JsonParser, DeserializationContext)},
 * driven with a mocked JsonParser / DeserializationContext / PropertyBasedCreator so that each
 * branch of the property-based deserialization loop can be exercised deterministically.
 */
public class _deserializeUsingPropertiesTests {

    private enum TestEnum { ALPHA, BETA }

    private static final JsonMapper MAPPER = JsonMapper.builder().build();

    private EnumMapDeserializer deserializer;
    private PropertyBasedCreator creator;
    private PropertyValueBuffer buffer;
    private KeyDeserializer keyDeserializer;
    private ValueDeserializer<Object> valueDeserializer;
    private JsonParser parser;
    private DeserializationContext ctxt;

    @Before
    @SuppressWarnings("unchecked")
    public void setUp() {
        JavaType enumMapType = MAPPER.getTypeFactory()
                .constructMapType(EnumMap.class, TestEnum.class, String.class);
        keyDeserializer = mock(KeyDeserializer.class);
        valueDeserializer = mock(ValueDeserializer.class);
        parser = mock(JsonParser.class);
        ctxt = mock(DeserializationContext.class);
        creator = mock(PropertyBasedCreator.class);
        buffer = mock(PropertyValueBuffer.class);

        deserializer = new EnumMapDeserializer(enumMapType, mock(ValueInstantiator.class),
                keyDeserializer, valueDeserializer, null, null);
        deserializer._propertyBasedCreator = creator;
        when(creator.startBuilding(parser, ctxt, null, false)).thenReturn(buffer);
    }

    @Test
    public void testBasicBufferingOfTwoKnownEntries() throws Exception {
        EnumMap<TestEnum, String> built = new EnumMap<TestEnum, String>(TestEnum.class);
        built.put(TestEnum.ALPHA, "first");
        built.put(TestEnum.BETA, "second");

        when(parser.isExpectedStartObjectToken()).thenReturn(true);
        when(parser.nextName()).thenReturn("ALPHA", "BETA", null);
        when(parser.nextToken()).thenReturn(JsonToken.VALUE_STRING);
        when(keyDeserializer.deserializeKey("ALPHA", ctxt)).thenReturn(TestEnum.ALPHA);
        when(keyDeserializer.deserializeKey("BETA", ctxt)).thenReturn(TestEnum.BETA);
        when(valueDeserializer.deserialize(parser, ctxt)).thenReturn("first", "second");
        when(creator.build(ctxt, buffer)).thenReturn(built);

        EnumMap<?, ?> result = deserializer._deserializeUsingProperties(parser, ctxt);

        assertSame(built, result);
        InOrder order = inOrder(buffer);
        order.verify(buffer).bufferMapProperty(TestEnum.ALPHA, "first");
        order.verify(buffer).bufferMapProperty(TestEnum.BETA, "second");
        verify(creator).build(ctxt, buffer);
    }

    @Test
    public void testCreatorPropertyTriggersBuildAndContinuesWithRemainingContent() throws Exception {
        EnumMap<TestEnum, String> built = new EnumMap<TestEnum, String>(TestEnum.class);
        SettableBeanProperty creatorProperty = mock(SettableBeanProperty.class);

        when(parser.isExpectedStartObjectToken()).thenReturn(true);
        when(parser.nextName()).thenReturn("ALPHA", null);
        when(parser.nextToken()).thenReturn(JsonToken.VALUE_STRING);
        when(creator.findCreatorProperty("ALPHA")).thenReturn(creatorProperty);
        when(creatorProperty.deserialize(parser, ctxt)).thenReturn("creatorValue");
        when(buffer.assignParameter(creatorProperty, "creatorValue")).thenReturn(true);
        when(creator.build(ctxt, buffer)).thenReturn(built);

        EnumMap<?, ?> result = deserializer._deserializeUsingProperties(parser, ctxt);

        assertSame(built, result);
        verify(creatorProperty).deserialize(parser, ctxt);
        verify(buffer).assignParameter(creatorProperty, "creatorValue");
        verify(creator).build(ctxt, buffer);
    }

    @Test
    public void testPropertyTokenEntryPointUsesCurrentName() throws Exception {
        EnumMap<TestEnum, String> built = new EnumMap<TestEnum, String>(TestEnum.class);

        when(parser.isExpectedStartObjectToken()).thenReturn(false);
        when(parser.hasToken(JsonToken.PROPERTY_NAME)).thenReturn(true);
        when(parser.currentName()).thenReturn("ALPHA");
        when(parser.nextName()).thenReturn(null);
        when(parser.nextToken()).thenReturn(JsonToken.VALUE_STRING);
        when(keyDeserializer.deserializeKey("ALPHA", ctxt)).thenReturn(TestEnum.ALPHA);
        when(valueDeserializer.deserialize(parser, ctxt)).thenReturn("value");
        when(creator.build(ctxt, buffer)).thenReturn(built);

        EnumMap<?, ?> result = deserializer._deserializeUsingProperties(parser, ctxt);

        assertSame(built, result);
        verify(buffer).bufferMapProperty(TestEnum.ALPHA, "value");
    }

    @Test
    public void testEmptyObjectBuildsWithoutBufferedProperties() throws Exception {
        EnumMap<TestEnum, String> built = new EnumMap<TestEnum, String>(TestEnum.class);

        when(parser.isExpectedStartObjectToken()).thenReturn(true);
        when(parser.nextName()).thenReturn(null);
        when(creator.build(ctxt, buffer)).thenReturn(built);

        EnumMap<?, ?> result = deserializer._deserializeUsingProperties(parser, ctxt);

        assertSame(built, result);
        verify(buffer, never()).bufferMapProperty(any(), any());
        verify(creator).build(ctxt, buffer);
    }

    @Test
    public void testUnknownEnumKeyReturnsWeirdStringValueHandlingResult() throws Exception {
        when(parser.isExpectedStartObjectToken()).thenReturn(true);
        when(parser.nextName()).thenReturn("UNKNOWN_KEY");
        when(parser.nextToken()).thenReturn(JsonToken.VALUE_STRING);
        when(keyDeserializer.deserializeKey("UNKNOWN_KEY", ctxt)).thenReturn(null);
        when(ctxt.isEnabled(EnumFeature.READ_UNKNOWN_ENUM_VALUES_AS_NULL)).thenReturn(false);
        // mocked DeserializationContext.handleWeirdStringValue(...) returns null by default

        EnumMap<?, ?> result = deserializer._deserializeUsingProperties(parser, ctxt);

        assertNull(result);
        verify(ctxt).handleWeirdStringValue(eq(TestEnum.class), eq("UNKNOWN_KEY"), anyString(), any());
        verify(buffer, never()).bufferMapProperty(any(), any());
    }

    @Test
    public void testUnknownEnumKeyWithReadAsNullFeatureSkipsEntryAndValue() throws Exception {
        EnumMap<TestEnum, String> built = new EnumMap<TestEnum, String>(TestEnum.class);

        when(parser.isExpectedStartObjectToken()).thenReturn(true);
        when(parser.nextName()).thenReturn("UNKNOWN_KEY", "BETA", null);
        when(parser.nextToken()).thenReturn(JsonToken.VALUE_STRING);
        when(keyDeserializer.deserializeKey("UNKNOWN_KEY", ctxt)).thenReturn(null);
        when(keyDeserializer.deserializeKey("BETA", ctxt)).thenReturn(TestEnum.BETA);
        when(ctxt.isEnabled(EnumFeature.READ_UNKNOWN_ENUM_VALUES_AS_NULL)).thenReturn(true);
        when(valueDeserializer.deserialize(parser, ctxt)).thenReturn("betaValue");
        when(creator.build(ctxt, buffer)).thenReturn(built);

        EnumMap<?, ?> result = deserializer._deserializeUsingProperties(parser, ctxt);

        assertSame(built, result);
        verify(parser).skipChildren();
        verify(buffer).bufferMapProperty(TestEnum.BETA, "betaValue");
    }

    @Test
    public void testNullJsonValueIsResolvedThroughValueDeserializerNullValue() throws Exception {
        EnumMap<TestEnum, String> built = new EnumMap<TestEnum, String>(TestEnum.class);

        when(parser.isExpectedStartObjectToken()).thenReturn(true);
        when(parser.nextName()).thenReturn("ALPHA", null);
        when(parser.nextToken()).thenReturn(JsonToken.VALUE_NULL);
        when(keyDeserializer.deserializeKey("ALPHA", ctxt)).thenReturn(TestEnum.ALPHA);
        when(valueDeserializer.getNullValue(ctxt)).thenReturn("NULL_SENTINEL");
        when(creator.build(ctxt, buffer)).thenReturn(built);

        EnumMap<?, ?> result = deserializer._deserializeUsingProperties(parser, ctxt);

        assertSame(built, result);
        verify(buffer).bufferMapProperty(TestEnum.ALPHA, "NULL_SENTINEL");
    }

    @Test
    public void testValueDeserializationFailureIsWrappedAndPropagated() throws Exception {
        when(parser.isExpectedStartObjectToken()).thenReturn(true);
        when(parser.nextName()).thenReturn("ALPHA", null);
        when(parser.nextToken()).thenReturn(JsonToken.VALUE_STRING);
        when(keyDeserializer.deserializeKey("ALPHA", ctxt)).thenReturn(TestEnum.ALPHA);
        when(valueDeserializer.deserialize(parser, ctxt)).thenThrow(new RuntimeException("boom"));

        try {
            deserializer._deserializeUsingProperties(parser, ctxt);
            fail("Expected an exception to be propagated when value deserialization fails");
        } catch (RuntimeException expected) {
            // expected: failure must not be silently swallowed
        }
        verify(buffer, never()).bufferMapProperty(any(), any());
    }
}