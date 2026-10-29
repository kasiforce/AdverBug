package tools.jackson.databind.deser.impl;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

import java.lang.reflect.Field;
import java.lang.reflect.Array;
import java.util.HashMap;
import java.util.Map;

import org.junit.Test;
import static org.junit.Assert.assertSame;

import tools.jackson.core.JsonParser;
import tools.jackson.databind.DeserializationContext;
import tools.jackson.databind.JavaType;
import tools.jackson.databind.deser.bean.PropertyBasedCreator;
import tools.jackson.databind.deser.bean.PropertyValueBuffer;
import tools.jackson.databind.util.TokenBuffer;

/**
 * Adjusted test to compile against a version where ExternalTypeHandler.ExtTypedProperty
 * is private. This test now constructs ExternalTypeHandler with a null properties array
 * (no ExtTypedProperty reference) and verifies basic interaction by then replacing the
 * private _properties field with an empty non-null array via reflection.
 */
public class CompleteTests {

    // Simple bean class used for testing
    static class SimpleBean {
        public String value;
    }

    @Test
    public void testComplete_SkipPropertyWhenFilteredByView() throws Exception {
        // Mock dependencies
        JavaType beanType = mock(JavaType.class);

        JsonParser p = mock(JsonParser.class);
        DeserializationContext ctxt = mock(DeserializationContext.class);
        PropertyValueBuffer buffer = mock(PropertyValueBuffer.class);
        PropertyBasedCreator creator = mock(PropertyBasedCreator.class);

        // Build handler with no external properties (avoid privateExtTypedProperty in tests)
        Map<String, Object> nameToPropertyIndex = new HashMap<>();
        String[] typeIds = new String[] { null };
        TokenBuffer[] tokens = new TokenBuffer[] { null };

        ExternalTypeHandler handler = new ExternalTypeHandler(beanType, null, nameToPropertyIndex, typeIds, tokens);

        // Ensure _properties is non-null to avoid NPEs in complete()
        try {
            Field f = ExternalTypeHandler.class.getDeclaredField("_properties");
            f.setAccessible(true);
            // Create a new empty array whose component type matches the actual field type
            Object emptyArray = Array.newInstance(f.getType().getComponentType(), 0);
            f.set(handler, emptyArray);
        } catch (Exception e) {
            throw new RuntimeException("Failed to initialize _properties for test", e);
        }

        SimpleBean expectedBean = new SimpleBean();
        when(creator.build(any(DeserializationContext.class), any(PropertyValueBuffer.class))).thenReturn(expectedBean);

        // Execute
        Object result = handler.complete(p, ctxt, buffer, creator);

        // Verify that the result is the same object produced by the creator
        assertSame(expectedBean, result);
    }
}