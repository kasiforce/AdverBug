package tools.jackson.databind.deser.impl;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import org.junit.Test;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.annotation.JsonSubTypes;
import com.fasterxml.jackson.annotation.JsonTypeInfo;
import com.fasterxml.jackson.annotation.JsonView;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;

/**
 * Tests for ExternalTypeHandler.complete() processing of buffered property
 * values and external type identifiers for creator-based beans: basic binding,
 * property ordering, explicit nulls, missing/unknown type ids, defaultImpl
 * fallback, natural scalar values, active JsonView filtering, non-creator
 * external type id properties, and type-id creator properties.
 */
public class CompleteTests {

    // View marker classes for @JsonView filtering
    public static class ViewLimited { }
    public static class ViewFull extends ViewLimited { }

    public static class Animal {
        public String name;
    }

    public static class Cat extends Animal {
        public int lives;
    }

    public static class Dog extends Animal {
        public boolean barks;
    }

    public static class CreatorPetBean {
        public int age;

        @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                property = "type")
        @JsonSubTypes({
            @JsonSubTypes.Type(value = Cat.class, name = "cat"),
            @JsonSubTypes.Type(value = Dog.class, name = "dog")
        })
        public Animal pet;

        @JsonCreator
        public CreatorPetBean(@JsonProperty("age") int age,
                @JsonProperty("pet") Animal pet) {
            this.age = age;
            this.pet = pet;
        }
    }

    public static class DefaultImplPetBean {
        @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                property = "type",
                defaultImpl = Cat.class)
        @JsonSubTypes({
            @JsonSubTypes.Type(value = Cat.class, name = "cat"),
            @JsonSubTypes.Type(value = Dog.class, name = "dog")
        })
        public Animal pet;

        @JsonCreator
        public DefaultImplPetBean(@JsonProperty("pet") Animal pet) {
            this.pet = pet;
        }
    }

    public static class NaturalCreatorBean {
        @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                property = "type")
        @JsonSubTypes({
            @JsonSubTypes.Type(value = Cat.class, name = "cat"),
            @JsonSubTypes.Type(value = Dog.class, name = "dog")
        })
        public Object pet;

        @JsonCreator
        public NaturalCreatorBean(@JsonProperty("pet") Object pet) {
            this.pet = pet;
        }
    }

    public static class ViewedCreatorBean {
        public int age;

        @JsonView(ViewFull.class)
        @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                property = "type")
        @JsonSubTypes({
            @JsonSubTypes.Type(value = Cat.class, name = "cat"),
            @JsonSubTypes.Type(value = Dog.class, name = "dog")
        })
        public Animal pet;

        @JsonCreator
        public ViewedCreatorBean(@JsonProperty("age") int age,
                @JsonProperty("pet") Animal pet) {
            this.age = age;
            this.pet = pet;
        }
    }

    public static class MixedCreatorBean {
        public int age;

        @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                property = "type")
        @JsonSubTypes({
            @JsonSubTypes.Type(value = Cat.class, name = "cat"),
            @JsonSubTypes.Type(value = Dog.class, name = "dog")
        })
        public Animal pet;

        @JsonCreator
        public MixedCreatorBean(@JsonProperty("age") int age) {
            this.age = age;
        }
    }

    public static class TypeIdCreatorBean {
        public String type;

        @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                property = "type")
        @JsonSubTypes({
            @JsonSubTypes.Type(value = Cat.class, name = "cat"),
            @JsonSubTypes.Type(value = Dog.class, name = "dog")
        })
        public Animal pet;

        @JsonCreator
        public TypeIdCreatorBean(@JsonProperty("type") String type,
                @JsonProperty("pet") Animal pet) {
            this.type = type;
            this.pet = pet;
        }
    }

    public static class NonStringTypeIdCreatorBean {
        public Object type;

        @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                property = "type")
        @JsonSubTypes({
            @JsonSubTypes.Type(value = Cat.class, name = "cat"),
            @JsonSubTypes.Type(value = Dog.class, name = "dog")
        })
        public Animal pet;

        @JsonCreator
        public NonStringTypeIdCreatorBean(@JsonProperty("type") Object type,
                @JsonProperty("pet") Animal pet) {
            this.type = type;
            this.pet = pet;
        }
    }

    private ObjectMapper mapper() {
        return JsonMapper.builder().build();
    }

    // Basic: external type id + value deserialized for creator properties
    @Test
    public void testExternalTypeIdWithCreatorProperty() throws Exception {
        CreatorPetBean bean = mapper().readValue(
                "{\"age\":3,\"type\":\"cat\",\"pet\":{\"name\":\"Tom\",\"lives\":9}}",
                CreatorPetBean.class);
        assertEquals(3, bean.age);
        assertNotNull(bean.pet);
        assertEquals(Cat.class, bean.pet.getClass());
        assertEquals("Tom", bean.pet.name);
        assertEquals(9, ((Cat) bean.pet).lives);
    }

    // Type id may appear after the value property; buffering must make this work
    @Test
    public void testExternalTypeIdAfterValueProperty() throws Exception {
        CreatorPetBean bean = mapper().readValue(
                "{\"pet\":{\"name\":\"Rex\"},\"type\":\"dog\",\"age\":4}",
                CreatorPetBean.class);
        assertEquals(4, bean.age);
        assertNotNull(bean.pet);
        assertEquals(Dog.class, bean.pet.getClass());
        assertEquals("Rex", bean.pet.name);
        assertFalse(((Dog) bean.pet).barks);
    }

    // Explicit null value without type id must be accepted, leaving property null
    @Test
    public void testExplicitNullValueWithoutTypeId() throws Exception {
        CreatorPetBean bean = mapper().readValue(
                "{\"age\":5,\"pet\":null}", CreatorPetBean.class);
        assertEquals(5, bean.age);
        assertNull(bean.pet);
    }

    // Object value without type id and without defaultImpl: must report missing type id
    @Test
    public void testMissingTypeIdForObjectValueFails() throws Exception {
        try {
            mapper().readValue("{\"age\":1,\"pet\":{\"name\":\"Tom\"}}",
                    CreatorPetBean.class);
            fail("Should not accept object value without external type id");
        } catch (JacksonException e) {
            String msg = String.valueOf(e.getMessage());
            assertTrue("Unexpected exception message: " + msg,
                    msg.contains("Missing external type id"));
        }
    }

    // Unregistered type id must be reported as an error
    @Test
    public void testUnknownTypeIdFails() throws Exception {
        try {
            mapper().readValue("{\"type\":\"fish\",\"pet\":{\"name\":\"Nemo\"}}",
                    CreatorPetBean.class);
            fail("Should not accept unknown external type id");
        } catch (JacksonException e) {
            // expected
        }
    }

    // [databind#94]: defaultImpl used when the external type id is missing
    @Test
    public void testDefaultImplUsedWhenTypeIdMissing() throws Exception {
        DefaultImplPetBean bean = mapper().readValue(
                "{\"pet\":{\"name\":\"Tom\",\"lives\":9}}", DefaultImplPetBean.class);
        assertNotNull(bean.pet);
        assertEquals(Cat.class, bean.pet.getClass());
        assertEquals("Tom", bean.pet.name);
        assertEquals(9, ((Cat) bean.pet).lives);
    }

    // [databind#3786]: natural scalar value without type id is bound directly
    @Test
    public void testNaturalScalarValueWithoutTypeId() throws Exception {
        NaturalCreatorBean bean = mapper().readValue(
                "{\"pet\":\"Tom\"}", NaturalCreatorBean.class);
        assertEquals("Tom", bean.pet);
    }

    // Object-typed property with explicit type id still binds the subtype
    @Test
    public void testTypedValueWithTypeIdOnObjectProperty() throws Exception {
        NaturalCreatorBean bean = mapper().readValue(
                "{\"type\":\"cat\",\"pet\":{\"name\":\"Tom\",\"lives\":9}}",
                NaturalCreatorBean.class);
        assertNotNull(bean.pet);
        assertEquals(Cat.class, bean.pet.getClass());
        assertEquals("Tom", ((Cat) bean.pet).name);
        assertEquals(9, ((Cat) bean.pet).lives);
    }

    // [databind#6055]: value property filtered out by the active view is skipped
    // entirely -- value left null instead of failing or being bound anyway
    @Test
    public void testViewFilteredExternalTypePropertyIsSkipped() throws Exception {
        final String JSON = "{\"age\":7,\"type\":\"cat\",\"pet\":{\"name\":\"Tom\",\"lives\":9}}";

        ViewedCreatorBean filtered = mapper().readerFor(ViewedCreatorBean.class)
                .withView(ViewLimited.class)
                .readValue(JSON);
        assertEquals(7, filtered.age);
        assertNull(filtered.pet);

        ViewedCreatorBean included = mapper().readerFor(ViewedCreatorBean.class)
                .withView(ViewFull.class)
                .readValue(JSON);
        assertEquals(7, included.age);
        assertNotNull(included.pet);
        assertEquals(Cat.class, included.pet.getClass());
        assertEquals("Tom", included.pet.name);
        assertEquals(9, ((Cat) included.pet).lives);
    }

    // Non-creator external type id property assigned after creator builds the bean
    @Test
    public void testNonCreatorExternalTypePropertySetAfterBuild() throws Exception {
        MixedCreatorBean bean = mapper().readValue(
                "{\"age\":3,\"type\":\"dog\",\"pet\":{\"name\":\"Rex\",\"barks\":true}}",
                MixedCreatorBean.class);
        assertEquals(3, bean.age);
        assertNotNull(bean.pet);
        assertEquals(Dog.class, bean.pet.getClass());
        assertEquals("Rex", bean.pet.name);
        assertTrue(((Dog) bean.pet).barks);
    }

    // [databind#999]: creator property receiving the type id itself (String)
    @Test
    public void testTypeIdExposedToCreatorProperty() throws Exception {
        TypeIdCreatorBean bean = mapper().readValue(
                "{\"type\":\"cat\",\"pet\":{\"name\":\"Tom\",\"lives\":9}}",
                TypeIdCreatorBean.class);
        assertEquals("cat", bean.type);
        assertNotNull(bean.pet);
        assertEquals(Cat.class, bean.pet.getClass());
        assertEquals("Tom", bean.pet.name);
    }

    // [databind#1328]: non-String creator property for the type id deserialized
    // via its own deserializer from a buffered TokenBuffer
    @Test
    public void testNonStringTypeIdExposedToCreatorProperty() throws Exception {
        NonStringTypeIdCreatorBean bean = mapper().readValue(
                "{\"type\":\"dog\",\"pet\":{\"name\":\"Rex\",\"barks\":true}}",
                NonStringTypeIdCreatorBean.class);
        assertEquals("dog", bean.type);
        assertNotNull(bean.pet);
        assertEquals(Dog.class, bean.pet.getClass());
        assertEquals("Rex", bean.pet.name);
        assertTrue(((Dog) bean.pet).barks);
    }
}