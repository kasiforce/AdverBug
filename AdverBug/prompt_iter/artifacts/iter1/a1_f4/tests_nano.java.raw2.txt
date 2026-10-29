package tools.jackson.databind.deser.impl;

import static org.junit.Assert.assertSame;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

import java.util.HashMap;
import java.util.Map;

import org.junit.Test;

import tools.jackson.core.JsonParser;
import tools.jackson.databind.DeserializationContext;
import tools.jackson.databind.JavaType;
import tools.jackson.databind.deser.SettableBeanProperty;
import tools.jackson.databind.deser.bean.PropertyBasedCreator;
import tools.jackson.databind.deser.bean.PropertyValueBuffer;
import tools.jackson.databind.util.TokenBuffer;

public class CompleteTests {

    // A dummy view class for testing active view filtering
    private static class DummyView {}

    @Test
    public void test_complete_skips_property_filtered_by_view_and_buildsBean() throws Exception {
        // Mocks
        DeserializationContext ctxt = mock(DeserializationContext.class);
        when(ctxt.getActiveView()).thenReturn(DummyView.class);

        PropertyBasedCreator creator = mock(PropertyBasedCreator.class);
        Object expectedBean = new Object();
        // Creator should build the bean when invoked
        when(creator.build(eq(ctxt), any(PropertyValueBuffer.class))).thenReturn(expectedBean);

        PropertyValueBuffer buffer = mock(PropertyValueBuffer.class);

        SettableBeanProperty prop = mock(SettableBeanProperty.class);
        // Property is not visible in the active view, so it should be skipped
        when(prop.visibleInView(eq(DummyView.class))).thenReturn(false);
        when(prop.isCreatorProperty()).thenReturn(false);
        // set() will be invoked later for non-creator properties
        doNothing().when(prop).set(any(DeserializationContext.class), any(), any());

        // ExtTypedProperty mock: its property returns the mock prop
        ExternalTypeHandler.ExtTypedProperty extProp = mock(ExternalTypeHandler.ExtTypedProperty.class);
        when(extProp.getProperty()).thenReturn(prop);
        when(extProp.getTypePropertyName()).thenReturn("typeName");
        when(extProp.hasDefaultType()).thenReturn(false);
        when(extProp.getTypeProperty()).thenReturn(null);

        ExtTypedProperty[] properties = new ExtTypedProperty[] { extProp };
        String[] typeIds = new String[] { "typeId" };
        TokenBuffer[] tokens = new TokenBuffer[] { null }; // not used due to view filter

        // The handler under test (beanType can be null for test purposes)
        ExternalTypeHandler handler = new ExternalTypeHandler(null, properties, new HashMap<>(), typeIds, tokens);

        JsonParser p = mock(JsonParser.class); // not used in this path
        Object bean = handler.complete(p, ctxt, buffer, creator);

        // Assertions
        assertSame(expectedBean, bean);
        verify(creator).build(eq(ctxt), eq(buffer));
        // Ensure non-creator property would be set with null value if reached after creation
        verify(prop).set(eq(ctxt), eq(expectedBean), isNull());
    }
}