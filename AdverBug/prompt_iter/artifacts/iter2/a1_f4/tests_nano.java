import org.junit.Test;
import static org.junit.Assert.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import java.util.HashMap;
import java.util.Map;

import tools.jackson.core.JsonParser;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.DeserializationContext;
import tools.jackson.databind.JavaType;
import tools.jackson.databind.type.TypeFactory;
import tools.jackson.databind.TypeFactory;
import tools.jackson.databind.deser.SettableBeanProperty;
import tools.jackson.databind.deser.bean.PropertyBasedCreator;
import tools.jackson.databind.deser.bean.PropertyValueBuffer;
import tools.jackson.databind.deser.impl.ExternalTypeHandler;
import tools.jackson.databind.util.TokenBuffer;

public class CompleteTests {

    // Simple bean used for testing creator path
    public static class TestBean {
        public Object value;
    }

    // A tiny subclass to override the protected _deserialize behavior for deterministic tests
    protected static class TestExternalTypeHandler extends ExternalTypeHandler {
        public TestExternalTypeHandler(JavaType beanType,
                                     ExtTypedProperty[] properties,
                                     Map<String, Object> nameToPropertyIndex,
                                     String[] typeIds,
                                     TokenBuffer[] tokens) {
            super(beanType, properties, nameToPropertyIndex, typeIds, tokens);
        }

        @Override
        protected Object _deserialize(JsonParser p, DeserializationContext ctxt,
                                    int index, String typeId) throws JacksonException {
            // deterministic value for testing
            return 42;
        }
    }

    @Test
    public void testComplete_AssignsCreatorParameter() throws Exception {
        // Prepare bean type
        JavaType beanType = TypeFactory.createDefaultInstance().constructType(TestBean.class);

        // Mocks
        ExternalTypeHandler.ExtTypedProperty extPropMock = mock(ExternalTypeHandler.ExtTypedProperty.class);
        SettableBeanProperty propMock = mock(SettableBeanProperty.class);
        PropertyBasedCreator creatorMock = mock(PropertyBasedCreator.class);
        PropertyValueBuffer bufferMock = mock(PropertyValueBuffer.class);
        JsonParser p = mock(JsonParser.class);
        DeserializationContext ctxt = mock(DeserializationContext.class);

        // TokenBuffer for this property
        TokenBuffer tb = new TokenBuffer();
        TokenBuffer[] tokens = new TokenBuffer[]{tb};

        // Type id
        String[] typeIds = new String[]{"typeX"};

        // Property setup
        when(extPropMock.getProperty()).thenReturn(propMock);
        when(extPropMock.hasDefaultType()).thenReturn(false);
        when(propMock.isCreatorProperty()).thenReturn(true);
        when(propMock.visibleInView(any())).thenReturn(true);
        // Type for the property (not used by _deserialize override, but required)
        JavaType dummyType = TypeFactory.createDefaultInstance().constructType(Object.class);
        when(propMock.getType()).thenReturn(dummyType);

        // Creator build behavior
        TestBean createdBean = new TestBean();
        when(creatorMock.build(any(DeserializationContext.class), any(PropertyValueBuffer.class)))
                .thenReturn(createdBean);

        // Build handler using the test subclass
        Map<String, Object> nameToPropertyIndex = new HashMap<>();
        ExternalTypeHandler handler = new TestExternalTypeHandler(beanType,
                new ExternalTypeHandler.ExtTypedProperty[]{extPropMock},
                nameToPropertyIndex,
                typeIds,
                tokens);

        // Call complete
        TestBean result = (TestBean) handler.complete(p, ctxt, bufferMock, creatorMock);

        // Verify that creator buffer received the parameter for the creator property
        verify(bufferMock).assignParameter(eq(propMock), eq(42));
        // And that builder was invoked with the buffer
        verify(creatorMock).build(eq(ctxt), eq(bufferMock));
        // Return bean should be the one created by the creator
        assertSame(createdBean, result);
    }

    @Test
    public void testComplete_SkipPropertyWhenFilteredByView() throws Exception {
        // Prepare bean type
        JavaType beanType = TypeFactory.createDefaultInstance().constructType(TestBean.class);

        // Mocks
        ExternalTypeHandler.ExtTypedProperty extPropMock = mock(ExternalTypeHandler.ExtTypedProperty.class);
        SettableBeanProperty propMock = mock(SettableBeanProperty.class);
        PropertyBasedCreator creatorMock = mock(PropertyBasedCreator.class);
        PropertyValueBuffer bufferMock = mock(PropertyValueBuffer.class);
        JsonParser p = mock(JsonParser.class);
        DeserializationContext ctxt = mock(DeserializationContext.class);

        // TokenBuffer for this property
        TokenBuffer tb = new TokenBuffer();
        TokenBuffer[] tokens = new TokenBuffer[]{tb};

        // Type id
        String[] typeIds = new String[]{"typeY"};

        // Active view class and visibility behavior: property not visible in view
        class ViewA {}
        when(ctxt.getActiveView()).thenReturn(ViewA.class);

        when(extPropMock.getProperty()).thenReturn(propMock);
        when(extPropMock.hasDefaultType()).thenReturn(false);
        when(propMock.isCreatorProperty()).thenReturn(false);
        // Property is not visible in the active view
        when(propMock.visibleInView(eq((Class<?>) ViewA.class))).thenReturn(false);

        // Build handler using the test subclass
        Map<String, Object> nameToPropertyIndex = new HashMap<>();
        ExternalTypeHandler handler = new TestExternalTypeHandler(beanType,
                new ExternalTypeHandler.ExtTypedProperty[]{extPropMock},
                nameToPropertyIndex,
                typeIds,
                tokens);

        // Call complete
        Object result = handler.complete(p, ctxt, bufferMock, creatorMock);

        // Since the property is filtered by view, no assignment should occur
        verify(bufferMock, never()).assignParameter(any(), any());
        // The method still returns a bean instance (could be created by creator; here we don't care)
        assertNotNull(result);
    }
}