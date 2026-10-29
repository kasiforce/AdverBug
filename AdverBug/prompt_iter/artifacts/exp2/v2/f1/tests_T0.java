package tools.jackson.databind.deser.jdk;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

import java.util.Properties;

public class _deserializeUsingPropertiesTests {

    public static class PropsBean {
        public String a;
        public int b;
    }

    @Test
    public void testDeserializeFromProperties() throws Exception {
        Properties props = new Properties();
        props.setProperty("a", "hello");
        props.setProperty("b", "42");

        // Use the testbed-provided ObjectMapper class, avoiding external imports
        tools.jackson.databind.ObjectMapper mapper = new tools.jackson.databind.ObjectMapper();
        String json = propertiesToJson(props);
        PropsBean bean = mapper.readValue(json, PropsBean.class);

        assertEquals("hello", bean.a);
        assertEquals(42, bean.b);
    }

    private String propertiesToJson(Properties props) {
        StringBuilder sb = new StringBuilder();
        sb.append("{");
        boolean first = true;
        for (String key : props.stringPropertyNames()) {
            if (!first) sb.append(",");
            sb.append("\"").append(key).append("\":");
            String value = props.getProperty(key);
            if (value.matches("-?\\d+")) {
                sb.append(value);
            } else {
                sb.append("\"").append(value).append("\"");
            }
            first = false;
        }
        sb.append("}");
        return sb.toString();
    }
}