package tools.jackson.databind.deser.jdk;

import static org.junit.Assert.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import java.util.*;

import org.junit.Test;

import tools.jackson.core.JsonToken;
import tools.jackson.core.JsonTokenId;
import tools.jackson.databind.DeserializationContext;

import tools.jackson.core.JsonParser;

public class DeserializeTests {

    @Test
    public void testEndObjectReturnsIntoValue() throws Exception {
        UntypedObjectDeserializerNR des = new UntypedObjectDeserializerNR();
        UntypedObjectDeserializerNR spy = spy(des);
        DeserializationContext ctxt = mock(DeserializationContext.class);
        JsonParser p = mock(JsonParser.class);

        when(p.currentTokenId()).thenReturn(JsonTokenId.ID_END_OBJECT);

        Map<String, Object> into = new HashMap<>();
        into.put("a", "b");

        Object result = spy.deserialize(p, ctxt, into);

        assertSame("intoValue should be returned unchanged", into, result);
    }

    @Test
    public void testStartObjectToEndReturnsIntoValue() throws Exception {
        UntypedObjectDeserializerNR des = new UntypedObjectDeserializerNR();
        UntypedObjectDeserializerNR spy = spy(des);
        DeserializationContext ctxt = mock(DeserializationContext.class);
        JsonParser p = mock(JsonParser.class);

        when(p.currentTokenId()).thenReturn(JsonTokenId.ID_START_OBJECT);
        when(p.nextToken()).thenReturn(JsonToken.END_OBJECT);

        Map<String, Object> into = new HashMap<>();
        into.put("a", "b");

        Object result = spy.deserialize(p, ctxt, into);

        assertSame("intoValue should be returned when object is empty", into, result);
    }

    @Test
    public void testPropertyNameMergesIntoMap() throws Exception {
        UntypedObjectDeserializerNR des = new UntypedObjectDeserializerNR();
        UntypedObjectDeserializerNR spy = spy(des);
        DeserializationContext ctxt = mock(DeserializationContext.class);
        JsonParser p = mock(JsonParser.class);

        final String oldVal = "oldValue";
        final String keyName = "k";

        when(p.currentTokenId()).thenReturn(JsonTokenId.ID_PROPERTY_NAME);
        when(p.currentName()).thenReturn(keyName);
        when(p.nextToken()).thenReturn(JsonToken.VALUE_STRING); // value token
        when(p.nextName()).thenReturn((String) null);

        Map<String, Object> into = new HashMap<>();
        into.put(keyName, oldVal);

        // When nested deserialization happens with the old value, return a new value
        doReturn("newValue").when(spy).deserialize(any(JsonParser.class), any(DeserializationContext.class), eq(oldVal));

        Object result = spy.deserialize(p, ctxt, into);

        assertSame("intoValue should be returned after merge", into, result);
        assertEquals("Value should be updated to newValue", "newValue", into.get(keyName));
    }

    @Test
    public void testStartArrayAppendsToCollection() throws Exception {
        UntypedObjectDeserializerNR des = new UntypedObjectDeserializerNR();
        UntypedObjectDeserializerNR spy = spy(des);
        DeserializationContext ctxt = mock(DeserializationContext.class);
        JsonParser p = mock(JsonParser.class);

        when(p.currentTokenId()).thenReturn(JsonTokenId.ID_START_ARRAY);
        // First nextToken() returns a value (to enter loop), second nextToken() ends the array
        when(p.nextToken()).thenReturn(JsonToken.VALUE_STRING, JsonToken.END_ARRAY);

        // Stub 2-arg deserialize to supply new elements for the array
        doReturn("X").when(spy).deserialize(any(JsonParser.class), any(DeserializationContext.class));

        List<String> into = new ArrayList<>();
        Object result = spy.deserialize(p, ctxt, into);

        assertSame("intoValue should be returned after appending", into, result);
        assertEquals(1, into.size());
        assertEquals("X", into.get(0));
    }

    @Test
    public void testStartArrayEmptyReturnsIntoValue() throws Exception {
        UntypedObjectDeserializerNR des = new UntypedObjectDeserializerNR();
        UntypedObjectDeserializerNR spy = spy(des);
        DeserializationContext ctxt = mock(DeserializationContext.class);
        JsonParser p = mock(JsonParser.class);

        when(p.currentTokenId()).thenReturn(JsonTokenId.ID_START_ARRAY);
        when(p.nextToken()).thenReturn(JsonToken.END_ARRAY);

        List<String> into = new ArrayList<>();
        Object result = spy.deserialize(p, ctxt, into);

        assertSame("intoValue should be returned when array is empty", into, result);
    }

    @Test
    public void testNonMergingUsesDefaultDeserialization() throws Exception {
        UntypedObjectDeserializerNR nonMerging = new UntypedObjectDeserializerNR(true);
        UntypedObjectDeserializerNR spy = spy(nonMerging);
        DeserializationContext ctxt = mock(DeserializationContext.class);
        JsonParser p = mock(JsonParser.class);

        // Use doReturn to avoid invoking the real 2-arg method during stubbing on a spy
        doReturn("mergedVal").when(spy).deserialize(any(JsonParser.class), any(DeserializationContext.class));

        Object result = spy.deserialize(p, ctxt, new ArrayList<>());

        assertEquals("mergedVal", result);
    }
}