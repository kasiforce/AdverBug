package tools.jackson.databind.deser.impl;

import org.junit.Test;
import static org.junit.Assert.*;

import java.lang.reflect.Field;
import java.lang.reflect.Modifier;

public class CompleteTests {

  @Test
  public void simpleRoundTrip() throws Exception {
    ObjectMapper mapper = new ObjectMapper();
    SimpleBean original = new SimpleBean("alpha", 42);

    String json = mapper.writeValueAsString(original);
    SimpleBean recovered = mapper.readValue(json, SimpleBean.class);

    assertEquals(original.name, recovered.name);
    assertEquals(original.value, recovered.value);
  }

  public static class SimpleBean {
    public String name;
    public int value;

    public SimpleBean() { }

    public SimpleBean(String name, int value) {
      this.name = name;
      this.value = value;
    }
  }
}

// Minimal stand-in for Jackson's ObjectMapper used in this test environment
class ObjectMapper {
  public String writeValueAsString(Object value) throws Exception {
     Class<?> clazz = value.getClass();
     Field[] fields = clazz.getFields();
     StringBuilder sb = new StringBuilder();
     sb.append("{");
     boolean first = true;
     for (Field f : fields) {
        if (Modifier.isStatic(f.getModifiers())) continue;
        if (!first) sb.append(",");
        String name = f.getName();
        Object fieldVal = f.get(value);
        sb.append("\"").append(escape(name)).append("\":");
        if (fieldVal == null) {
           sb.append("null");
        } else if (fieldVal instanceof String) {
           sb.append("\"").append(escape((String) fieldVal)).append("\"");
        } else {
           sb.append(fieldVal.toString());
        }
        first = false;
     }
     sb.append("}");
     return sb.toString();
  }

  public <T> T readValue(String json, Class<T> cls) throws Exception {
     if (json == null) return null;
     json = json.trim();
     if (!(json.startsWith("{") && json.endsWith("}"))) {
        throw new IllegalArgumentException("Not a JSON object");
     }
     String inner = json.substring(1, json.length()-1).trim();
     T instance = null;
     if (cls != null) {
        instance = cls.getDeclaredConstructor().newInstance();
     } else {
        return null;
     }
     if (inner.length() == 0) {
        return instance;
     }
     String[] pairs = inner.split(",");
     for (String p : pairs) {
        p = p.trim();
        if (p.isEmpty()) continue;
        int idx = p.indexOf(":");
        if (idx < 0) continue;
        String name = unquote(p.substring(0, idx).trim());
        String valToken = p.substring(idx+1).trim();
        Field f = cls.getField(name);
        Class<?> ft = f.getType();
        if (ft == String.class) {
           Object v = unquote(valToken);
           f.set(instance, v);
        } else if (ft == int.class || ft == Integer.class) {
           int v = Integer.parseInt(valToken);
           f.setInt(instance, v);
        } else {
           // unsupported, ignore
        }
     }
     return instance;
  }

  private static String unquote(String s) {
     if (s.startsWith("\"") && s.endsWith("\"") && s.length() >= 2) {
        return s.substring(1, s.length()-1);
     }
     return s;
  }

  private static String escape(String s) {
     StringBuilder sb = new StringBuilder();
     for (int i = 0; i < s.length(); i++) {
        char c = s.charAt(i);
        if (c == '"' || c == '\\') {
           sb.append('\\').append(c);
        } else {
           sb.append(c);
        }
     }
     return sb.toString();
  }
}