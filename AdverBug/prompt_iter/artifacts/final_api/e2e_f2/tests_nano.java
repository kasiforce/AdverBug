package tools.jackson.databind.deser.jdk;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;

import java.util.EnumMap;

import org.junit.Test;

import tools.jackson.core.JsonParser;
import tools.jackson.core.JsonToken;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.DeserializationContext;
import tools.jackson.databind.JavaType;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.deser.KeyDeserializer;
import tools.jackson.databind.deser.ValueDeserializer;
import tools.jackson.databind.deser.ValueInstantiator;
import tools.jackson.databind.deser.NullValueProvider;
import tools.jackson.databind.deser.jdk.EnumMapDeserializer;
import tools.jackson.databind.type.TypeFactory;
import tools.jackson.databind.jsontype.TypeDeserializer;

public class DeserializeTests {

    enum Color { RED, GREEN, BLUE }

    @Test
    public void testBasicEnumMapDeserialization() throws Exception {
        // Mocks and setup
        ValueInstantiator valueInstantiator = mock(ValueInstantiator.class);

        KeyDeserializer keyDeser = mock(KeyDeserializer.class);
        when(keyDeser.deserializeKey(anyString(), any(DeserializationContext.class)))
            .thenAnswer(inv -> Color.valueOf((String) inv.getArgument(0)));

        @SuppressWarnings("unchecked")
        ValueDeserializer<Object> valueDeser = mock(ValueDeserializer.class);
        when(valueDeser.deserialize(any(JsonParser.class), any(DeserializationContext.class)))
            .thenAnswer(inv -> {
                JsonParser p = (JsonParser) inv.getArgument(0);
                return p.getText();
            });
        // Ensure ObjectIdReader is null to avoid referring accumulator
        when(valueDeser.getObjectIdReader(any(DeserializationContext.class))).thenReturn(null);

        NullValueProvider nuller = mock(NullValueProvider.class);
        when(nuller.getNullValue(any(DeserializationContext.class))).thenReturn(null);

        DeserializationContext ctxt = mock(DeserializationContext.class);

        TypeFactory tf = TypeFactory.createDefaultInstance();
        JavaType mapType = tf.constructMapType(EnumMap.class, Color.class, String.class);

        EnumMapDeserializer deserializer = new EnumMapDeserializer(mapType, valueInstantiator, keyDeser, valueDeser, (TypeDeserializer) null, nuller);

        mapper = JsonMapper.builder().build();
        String json = "{\"RED\":\"apple\",\"GREEN\":\"banana\"}";
        JsonParser p = mapper.getFactory().createParser(json);

        EnumMap<Color, String> result = new EnumMap<>(Color.class);

        @SuppressWarnings("unchecked")
        EnumMap<Color, String> deserialized = (EnumMap<Color, String>) deserializer.deserialize(p, ctxt, result);

        assertNotNull(deserialized);
        assertEquals(2, deserialized.size());
        assertEquals("apple", deserialized.get(Color.RED));
        assertEquals("banana", deserialized.get(Color.GREEN));
    }

    @Test
    public void testEmptyObjectDeserializesToEmptyMap() throws Exception {
        // Mocks and setup
        ValueInstantiator valueInstantiator = mock(ValueInstantiator.class);

        KeyDeserializer keyDeser = mock(KeyDeserializer.class);
        when(keyDeser.deserializeKey(anyString(), any(DeserializationContext.class)))
            .thenAnswer(inv -> Color.valueOf((String) inv.getArgument(0)));

        @SuppressWarnings("unchecked")
        ValueDeserializer<Object> valueDeser = mock(ValueDeserializer.class);
        when(valueDeser.deserialize(any(JsonParser.class), any(DeserializationContext.class)))
            .thenAnswer(inv -> {
                JsonParser p = (JsonParser) inv.getArgument(0);
                return p.getText();
            });
        when(valueDeser.getObjectIdReader(any(DeserializationContext.class))).thenReturn(null);

        NullValueProvider nuller = mock(NullValueProvider.class);
        when(nuller.getNullValue(any(DeserializationContext.class))).thenReturn(null);

        DeserializationContext ctxt = mock(DeserializationContext.class);

        TypeFactory tf = TypeFactory.createDefaultInstance();
        JavaType mapType = tf.constructMapType(EnumMap.class, Color.class, String.class);

        EnumMapDeserializer deserializer = new EnumMapDeserializer(mapType, valueInstantiator, keyDeser, valueDeser, (TypeDeserializer) null, nuller);

        mapper = JsonMapper.builder().build();
        String json = "{}";
        JsonParser p = mapper.getFactory().createParser(json);

        EnumMap<Color, String> result = new EnumMap<>(Color.class);

        @SuppressWarnings("unchecked")
        EnumMap<Color, String> deserialized = (EnumMap<Color, String>) deserializer.deserialize(p, ctxt, result);

        assertNotNull(deserialized);
        assertEquals(0, deserialized.size());
    }

    @Test(expected = JacksonException.class)
    public void testUnknownEnumKeyThrowsJacksonException() throws Exception {
        // Mocks and setup
        ValueInstantiator valueInstantiator = mock(ValueInstantiator.class);

        KeyDeserializer keyDeser = mock(KeyDeserializer.class);
        when(keyDeser.deserializeKey(anyString(), any(DeserializationContext.class)))
            .thenAnswer(inv -> Color.valueOf((String) inv.getArgument(0))); // will throw for unknown key

        @SuppressWarnings("unchecked")
        ValueDeserializer<Object> valueDeser = mock(ValueDeserializer.class);
        when(valueDeser.deserialize(any(JsonParser.class), any(DeserializationContext.class)))
            .thenAnswer(inv -> {
                JsonParser p = (JsonParser) inv.getArgument(0);
                return p.getText();
            });
        when(valueDeser.getObjectIdReader(any(DeserializationContext.class))).thenReturn(null);

        NullValueProvider nuller = mock(NullValueProvider.class);
        when(nuller.getNullValue(any(DeserializationContext.class))).thenReturn(null);

        DeserializationContext ctxt = mock(DeserializationContext.class);

        TypeFactory tf = TypeFactory.createDefaultInstance();
        JavaType mapType = tf.constructMapType(EnumMap.class, Color.class, String.class);

        EnumMapDeserializer deserializer = new EnumMapDeserializer(mapType, valueInstantiator, keyDeser, valueDeser, (TypeDeserializer) null, nuller);

        mapper = JsonMapper.builder().build();
        String json = "{\"PURPLE\":\"x\"}";
        JsonParser p = mapper.getFactory().createParser(json);

        EnumMap<Color, String> result = new EnumMap<>(Color.class);

        deserializer.deserialize(p, ctxt, result); // should throw JacksonException
    }
}