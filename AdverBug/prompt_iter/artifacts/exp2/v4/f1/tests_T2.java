package tools.jackson.databind.deser.jdk;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.junit.Assert.assertSame;

import java.util.EnumMap;

import org.junit.Test;

import tools.jackson.core.JsonParser;
import tools.jackson.core.JsonToken;
import tools.jackson.databind.DeserializationContext;
import tools.jackson.databind.JavaType;
import tools.jackson.databind.cfg.EnumFeature;
import tools.jackson.databind.type.TypeFactory;
import tools.jackson.databind.deser.ValueInstantiator;
import tools.jackson.databind.deser.bean.PropertyBasedCreator;
import tools.jackson.databind.deser.bean.PropertyValueBuffer;
import tools.jackson.databind.deser.SettableBeanProperty;
import tools.jackson.databind.deser.impl.ObjectIdReader;
import tools.jackson.databind.deser.NullValueProvider;
import tools.jackson.databind.jsontype.TypeDeserializer;
import tools.jackson.databind.deser.jdk.EnumMapDeserializer;

/*
 * Tests for EnumMapDeserializer._deserializeUsingProperties
 * Adapted to compile in environments where KeyDeserializer/ValueDeserializer are not available.
 */
public class _deserializeUsingPropertiesTests {

    // A simple enum used for map keys in tests
    private enum SimpleEnum { A, B }

    @Test
    public void testDeserializeUsingProperties_propertyBasedCreatorPathBuildsMap() throws Exception {
        // Prepare JavaType for EnumMap<SimpleEnum, String>
        JavaType mapType = TypeFactory.createDefaultInstance().constructMapType(EnumMap.class, SimpleEnum.class, String.class);

        // Mock dependencies required by EnumMapDeserializer constructor
        ValueInstantiator valueInstantiator = mock(ValueInstantiator.class);

        // Construct deserializer with nulls for key/value deserializers
        EnumMapDeserializer deserializer = new EnumMapDeserializer(mapType, valueInstantiator, null, null, null, null) {
            @Override
            public EnumMap<?, ?> deserialize(JsonParser p, DeserializationContext ctxt, EnumMap value) {
                // Just return the map as-is for test purposes
                return value;
            }
        };

        // Create mocks for property-based creation path
        PropertyBasedCreator mockCreator = mock(PropertyBasedCreator.class);
        PropertyValueBuffer mockBuffer = mock(PropertyValueBuffer.class);
        SettableBeanProperty mockProp = mock(SettableBeanProperty.class);

        // Configure the property-based creation flow
        when(mockCreator.startBuilding(any(JsonParser.class), any(DeserializationContext.class), isNull(), eq(false)))
                .thenReturn(mockBuffer);
        when(mockCreator.findCreatorProperty("A")).thenReturn(mockProp);
        when(mockProp.deserialize(any(JsonParser.class), any(DeserializationContext.class))).thenReturn("VALUE");
        when(mockBuffer.assignParameter(eq(mockProp), eq("VALUE"))).thenReturn(true);

        EnumMap<SimpleEnum, String> created = new EnumMap<>(SimpleEnum.class);
        created.put(SimpleEnum.A, "VALUE");
        when(mockCreator.build(any(DeserializationContext.class), any(PropertyValueBuffer.class))).thenReturn(created);

        // Inject the mockCreator into the deserializer (protected field accessible in same package)
        deserializer._propertyBasedCreator = mockCreator;

        // Prepare JsonParser and DeserializationContext
        JsonParser p = mock(JsonParser.class);
        DeserializationContext ctxt = mock(DeserializationContext.class);

        // Simulate a JSON object with a single key "A"
        when(p.isExpectedStartObjectToken()).thenReturn(true);
        when(p.nextName()).thenReturn("A"); // keyName
        when(p.nextToken()).thenReturn(JsonToken.VALUE_STRING); // value token
        when(p.nextName()).thenReturn(null); // end of object

        // Execute
        @SuppressWarnings("unchecked")
        EnumMap<?, ?> result = deserializer._deserializeUsingProperties(p, ctxt);

        // Verify and assert
        assertSame("The returned map should be the same instance produced by the creator", created, result);
    }

    @Test
    public void testDeserializeUsingProperties_unknownEnumValueAsNullSkipsEntry() throws Exception {
        // Prepare JavaType for EnumMap<SimpleEnum, String>
        JavaType mapType = TypeFactory.createDefaultInstance().constructMapType(EnumMap.class, SimpleEnum.class, String.class);

        // Mock dependencies required by EnumMapDeserializer constructor
        ValueInstantiator valueInstantiator = mock(ValueInstantiator.class);

        // Construct deserializer with nulls for key/value deserializers
        EnumMapDeserializer deserializer = new EnumMapDeserializer(mapType, valueInstantiator, null, null, null, null) {
            @Override
            public EnumMap<?, ?> deserialize(JsonParser p, DeserializationContext ctxt, EnumMap value) {
                return value;
            }
        };

        // Create mocks for property-based creation path (no creator property for this key)
        PropertyBasedCreator mockCreator = mock(PropertyBasedCreator.class);
        PropertyValueBuffer mockBuffer = mock(PropertyValueBuffer.class);

        // For this test, no creator property should be found
        when(mockCreator.startBuilding(any(JsonParser.class), any(DeserializationContext.class), isNull(), eq(false)))
                .thenReturn(mockBuffer);
        when(mockCreator.findCreatorProperty("Unknown")).thenReturn(null);

        // Enable reading unknown enum values as null
        DeserializationContext ctxt = mock(DeserializationContext.class);
        when(ctxt.isEnabled(eq(EnumFeature.READ_UNKNOWN_ENUM_VALUES_AS_NULL))).thenReturn(true);

        // JSON parser setup
        JsonParser p = mock(JsonParser.class);
        when(p.isExpectedStartObjectToken()).thenReturn(true);
        when(p.nextName()).thenReturn("Unknown"); // keyName
        when(p.nextToken()).thenReturn(JsonToken.VALUE_STRING); // value token
        when(p.nextName()).thenReturn(null); // end of object
        // When unknown value is skipped
        when(p.skipChildren()).thenReturn(null);

        // Build a map to return after end
        EnumMap<SimpleEnum, String> emptyMap = new EnumMap<>(SimpleEnum.class);
        when(mockCreator.build(any(DeserializationContext.class), any(PropertyValueBuffer.class))).thenReturn(emptyMap);

        // Inject mocks
        deserializer._propertyBasedCreator = mockCreator;

        // Execute
        @SuppressWarnings("unchecked")
        EnumMap<?, ?> result = deserializer._deserializeUsingProperties(p, ctxt);

        // Verify that an empty map (skipped entry) is returned
        assertSame("Result should be the empty map produced by the builder after skipping unknown enum", emptyMap, result);
    }

}