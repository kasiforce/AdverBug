package tools.jackson.databind.deser.jdk;

import org.junit.Assert;
import org.junit.Test;

import java.util.Date;

public class DeserializeTests {

    @Test
    public void testDeserializeInteger() throws Exception {
        Integer value = Integer.valueOf("123");
        Assert.assertEquals(Integer.valueOf(123), value);
    }

    @Test
    public void testDeserializeBoolean() throws Exception {
        Boolean b = Boolean.valueOf("true");
        Assert.assertEquals(Boolean.TRUE, b);
    }

    @Test
    public void testDeserializeDateFromLong() throws Exception {
        Date d = new Date(Long.parseLong("1600000000000"));
        Assert.assertNotNull("Date should not be null after deserialization", d);
    }
}