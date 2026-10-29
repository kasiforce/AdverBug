package tools.jackson.databind.deser.impl;

import static org.junit.Assert.*;
import static org.mockito.Mockito.*;

import java.util.HashMap;
import java.util.Map;

import org.junit.Test;

import tools.jackson.core.JsonParser;
import tools.jackson.core.JsonToken;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.DeserializationContext;
import tools.jackson.databind.JavaType;
import tools.jackson.databind.deser.SettableBeanProperty;
import tools.jackson.databind.deser.bean.PropertyBasedCreator;
import tools.jackson.databind.deser.bean.PropertyValueBuffer;
import tools.jackson.databind.jsontype.TypeDeserializer;
import tools.jackson.databind.util.TokenBuffer;

public class CompleteTests {

    // Simple bean used by tests
    public static class MyBean {
        private Object value;

        public void setValue(Object v) {
            this.value = v;
        }

        public Object getValue() {
            return value;
        }
    }

    // Subclass to override internal deserialization for test predictability
    static class ReturningExternalTypeHandler extends ExternalTypeHandler {
        private final Object _ret;

        public ReturningExternalTypeHandler(JavaType beanType, ExtTypedProperty[] properties,
                                            Map<String, Object> nameToPropertyIndex,
                                            String[] typeIds, TokenBuffer[] tokens, Object ret) {
            super(beanType, properties, nameToPropertyIndex, typeIds, tokens);
            _ret = ret;
        }

        @Override
        protected Object _deserialize(JsonParser p, DeserializationContext ctxt, int i, Object value) throws JacksonException {
            return _ret;
        }

        @Override
        protected Object _deserializeMissingToken(JsonParser p, DeserializationContext ctxt, int i, String typeId) throws JacksonException {
            return null;
        }
    }

    // Lightweight ExtTypedProperty wrapper for mocks
    interface ExtTypedProperty {
        SettableBeanProperty getProperty();
        boolean hasDefaultType();
        String getTypePropertyName();
        String getDefaultTypeId(DeserializationContext ctxt);
        TypeProperty getTypeProperty();
        boolean visibleInView(Class<?> view);
    }

    // Placeholder for type property used in creator branches
    interface TypeProperty {
        boolean isCreatorProperty();
        Class<?> getType();
        Object getValueDeserializer();
    }

    @Test
    public void testCompleteAssignsDeserializedValueToBean() throws Exception {
        // Mock bean type and property wiring
        JavaType beanType = mock(JavaType.class);
        ExtTypedProperty mockExt = mock(ExtTypedProperty.class);
        SettableBeanProperty mockProp = mock(SettableBeanProperty.class);

        // Property setup
        when(mockExt.getProperty()).thenReturn(mockProp);
        when(mockProp.isCreatorProperty()).thenReturn(false);
        // Visible in view should pass
        when(mockProp.visibleInView(any())).thenReturn(true);

        // External-type handling defaults
        when(mockExt.hasDefaultType()).thenReturn(true);
        when(mockExt.getDefaultTypeId(any())).thenReturn("DefaultType");
        when(mockExt.getTypeProperty()).thenReturn(null);
        // TypePropertyName access not used in this test

        // Active view not used here (null)
        DeserializationContext ctxt = mock(DeserializationContext.class);
        when(ctxt.getActiveView()).thenReturn(null);

        // TokenBuffer with non-scalar start to avoid natural-type path
        TokenBuffer tb = new TokenBuffer(null);
        tb.writeStartObject();
        tb.writeFieldName("x");
        tb.writeString("y");
        tb.writeEndObject();

        TokenBuffer[] tokens = new TokenBuffer[]{tb};
        String[] typeIds = new String[]{null};
        ExtTypedProperty[] props = new ExtTypedProperty[]{mockExt};
        Map<String, Object> nameToPropertyIndex = new HashMap<>();

        PropertyValueBuffer buffer = mock(PropertyValueBuffer.class);
        PropertyBasedCreator creator = mock(PropertyBasedCreator.class);
        // Builder returns a concrete bean
        MyBean builtBean = new MyBean();
        when(creator.build(any(DeserializationContext.class), any(PropertyValueBuffer.class))).thenReturn(builtBean);

        // Override _deserialize to return a known value
        ReturningExternalTypeHandler handler = new ReturningExternalTypeHandler(
                beanType, props, nameToPropertyIndex, typeIds, tokens, "DESER-VAL"
        );

        // Ensure setter populates bean value using the value assigned
        doAnswer(invocation -> {
            Object beanArg = invocation.getArgument(1);
            Object val = invocation.getArgument(2);
            if (beanArg instanceof MyBean) {
                ((MyBean) beanArg).setValue(val);
            }
            return null;
        }).when(mockProp).set(any(DeserializationContext.class), any(Object.class), any(Object.class));

        Object result = handler.complete(mock(JsonParser.class), ctxt, buffer, creator);

        assertNotNull(result);
        assertTrue(result instanceof MyBean);
        assertEquals("DESER-VAL", ((MyBean) result).getValue());
    }

    @Test
    public void testMissingExternalTypeIdPropertyThrowsWhenConfigured() throws Exception {
        // Prepare mocks
        JavaType beanType = mock(JavaType.class);
        ExtTypedProperty mockExt = mock(ExtTypedProperty.class);
        SettableBeanProperty mockProp = mock(SettableBeanProperty.class);

        when(mockExt.getProperty()).thenReturn(mockProp);
        when(mockProp.isCreatorProperty()).thenReturn(false);
        when(mockProp.visibleInView(any())).thenReturn(true);

        // Simulate missing default type: should trigger error
        when(mockExt.hasDefaultType()).thenReturn(false);

        DeserializationContext ctxt = mock(DeserializationContext.class);
        when(ctxt.getActiveView()).thenReturn(null);

        // Ensure FAIL_ON_MISSING_EXTERNAL_TYPE_ID_PROPERTY is enabled
        when(ctxt.isEnabled(DeserializationFeature.FAIL_ON_MISSING_EXTERNAL_TYPE_ID_PROPERTY)).thenReturn(true);

        TokenBuffer tb = new TokenBuffer(null);
        tb.writeStartObject();
        tb.writeEndObject();

        TokenBuffer[] tokens = new TokenBuffer[]{tb};
        String[] typeIds = new String[]{null};
        ExtTypedProperty[] props = new ExtTypedProperty[]{mockExt};
        Map<String, Object> nameToPropertyIndex = new HashMap<>();

        PropertyValueBuffer buffer = mock(PropertyValueBuffer.class);
        PropertyBasedCreator creator = mock(PropertyBasedCreator.class);

        // We expect a JacksonException to be thrown due to missing external type id property
        boolean threw = false;
        try {
            ReturningExternalTypeHandler handler = new ReturningExternalTypeHandler(
                    beanType, props, nameToPropertyIndex, typeIds, tokens, null
            );
            handler.complete(mock(JsonParser.class), ctxt, buffer, creator);
        } catch (JacksonException ex) {
            threw = true;
        }

        assertTrue("Expected JacksonException due to missing external type id property", threw);
    }

}