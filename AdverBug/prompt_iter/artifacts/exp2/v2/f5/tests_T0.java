package tools.jackson.databind.deser.jdk;

import org.junit.Test;
import static org.junit.Assert.*;

public class DeserializeTests {

    public static class SimpleBean {
        public int value;
    }

    @Test
    public void testReflectionInstantiationAndFieldAccess() throws Exception {
        Class<?> cls = SimpleBean.class;
        Object instance = cls.getDeclaredConstructor().newInstance();

        // Access and modify the public field via reflection
        java.lang.reflect.Field f = cls.getField("value");
        f.setInt(instance, 123);

        int actual = f.getInt(instance);
        assertEquals(123, actual);
    }
}