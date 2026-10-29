public EnumMap<?,?> _deserializeUsingProperties(JsonParser p, DeserializationContext ctxt)
        throws JacksonException
    {
        final PropertyBasedCreator creator = _propertyBasedCreator;
        // null -> no ObjectIdReader for EnumMaps
        PropertyValueBuffer buffer = creator.startBuilding(p, ctxt, null, false);

        String keyName;
        if (p.isExpectedStartObjectToken()) {
            keyName = p.nextName();
        } else if (p.hasToken(JsonToken.PROPERTY_NAME)) {
            keyName = p.currentName();
        } else {
            keyName = null;
        }

        for (; keyName != null; keyName = p.nextName()) {
            JsonToken t = p.nextToken(); // to get to value
            // creator property?
            SettableBeanProperty prop = creator.findCreatorProperty(keyName);
            if (prop != null) {
                // Last property to set?
                if (buffer.assignParameter(prop, prop.deserialize(p, ctxt))) {
                    p.nextToken(); // from value to END_OBJECT or PROPERTY_NAME
                    EnumMap<?,?> result;
                    try {
                        result = (EnumMap<?,?>)creator.build(ctxt, buffer);
                    } catch (Exception e) {
                        return wrapAndThrow(ctxt, e, _containerType.getRawClass(), keyName);
                    }
                    return deserialize(p, ctxt, result);
                }
                continue;
            }
            // other property? needs buffering
            // but we need to let key deserializer handle it separately, nonetheless
            Enum<?> key = (Enum<?>) _keyDeserializer.deserializeKey(keyName, ctxt);
            if (key == null) {
                if (!ctxt.isEnabled(EnumFeature.READ_UNKNOWN_ENUM_VALUES_AS_NULL)) {
                    return (EnumMap<?,?>) ctxt.handleWeirdStringValue(_enumClass, keyName,
                            "value not one of declared Enum instance names for %s",
                            _containerType.getKeyType());
                }
                // 24-Mar-2012, tatu: Null won't work as a key anyway, so let's
                //  just skip the entry then. But we must skip the value as well, if so.
                p.skipChildren();
                continue;
            }
            Object value;

            try {
                if (t == JsonToken.VALUE_NULL) {
                    if (!_skipNullValues) {
                        continue;
                    }
                    value = null;
                } else {
                    value = _deserializeNoNullChecks(p, ctxt);
                }

                if (value == null) {
                    value = _nullProvider.getNullValue(ctxt);

                    if (value == null && _skipNullValues) {
                        continue;
                    }
                }
            } catch (Exception e) {
                wrapAndThrow(ctxt, e, _containerType.getRawClass(), keyName);
                return null;
            }
            buffer.bufferMapProperty(key, value);
        }
        // end of JSON object?
        // if so, can just construct and leave...
        try {
            return (EnumMap<?,?>)creator.build(ctxt, buffer);
        } catch (Exception e) {
            wrapAndThrow(ctxt, e, _containerType.getRawClass(), keyName);
            return null;
        }
    }