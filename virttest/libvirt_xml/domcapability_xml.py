"""
Module simplifying manipulation of XML described at
http://libvirt.org/formatdomaincaps.html
"""

import logging

from virttest import xml_utils
from virttest.libvirt_xml import accessors, base, xcepts

LOG = logging.getLogger("avocado." + __name__)


class DomCapabilityXML(base.LibvirtXMLBase):
    """
    Handler of libvirt domcapabilities operations.

    Properties:
        features:
            DomCapFeaturesXML instance to deal with domain features
    """

    __slots__ = ("features", "max")
    __schema_name__ = "domcapabilities"

    def __init__(self, virsh_instance=base.virsh):
        accessors.XMLElementNest(
            property_name="features",
            libvirtxml=self,
            parent_xpath="/",
            tag_name="features",
            subclass=DomCapFeaturesXML,
            subclass_dargs={"virsh_instance": virsh_instance},
        )
        accessors.XMLAttribute(
            "max", self, parent_xpath="/", tag_name="vcpu", attribute="max"
        )
        super(DomCapabilityXML, self).__init__(virsh_instance)
        result = self.__dict_get__("virsh").domcapabilities()
        self["xml"] = result.stdout_text.strip()

    def get_additional_feature_list(self, cpu_mode_name, ignore_features=("invtsc",)):
        """
        Get additional CPU features which explicitly specified by <feature>
        tag in cpu/mode[@name='host-model'] part of virsh domcapabilities.

        In libvirt 3.9 and above, domcapabilities give the overall features supported
        by current host/qemu/kvm via CPU model and a bunch of additional features. CPU
        model is one set of features defined by libvirt in '/usr/share/libvirt/cpu_map.xml'
        Specific features described in domcapabilities are additional features, the valid
        policy values are 'require' and 'disable', 'require' means the feature can be emulated
        by host/qemu/kvm, 'disable' which means feature is disabled by current system due to
        host CPU doesn't support or qemu/kvm has no ability to emulate it or some other
        reasons like the feature block migration and so on.

        Below is one snipped CPU host-model part output of domcapabilities.
        <feature> tag specify additional feature policy for one certain feature type.

        virsh domcapabilities  | xmllint -xpath "/domainCapabilities/cpu/mode[@name='host-model']" -
        <mode name="host-model" supported="yes">
            <model fallback="forbid">Skylake-Client</model>
            <vendor>Intel</vendor>
            <feature policy="require" name="ss"/>
            <feature policy="require" name="hypervisor"/>
            <feature policy="require" name="tsc_adjust"/>
            <feature policy="require" name="clflushopt"/>
            <feature policy="require" name="pdpe1gb"/>
            <feature policy="require" name="invtsc"/>
        </mode>

        :param cpu_mode_name: cpu mode name, must be 'host-model' since libvirt3.9
        :param ignore_features: features that need to be ignored
        :return: list of features, feature is dict-like, feature name is set to dict key,
                 feature policy is set to dict value.
                 returen is like [{'ss': 'require'}, {'pdpe1gb', 'require'}]
        """
        feature_list = []  # [{feature1: policy}, {feature2: policy}, ...]
        xmltreefile = self.__dict_get__("xml")
        try:
            for mode_node in xmltreefile.findall("/cpu/mode"):
                # Get mode which name attribute is 'host-model'
                if mode_node.get("name") == cpu_mode_name:
                    for feature in mode_node.findall("feature"):
                        item = {}
                        item[feature.get("name")] = feature.get("policy")
                        if ignore_features and item in ignore_features:
                            continue
                        feature_list.append(item)
        except AttributeError as elem_attr:
            LOG.warning("Failed to find attribute %s" % elem_attr)
            feature_list = []
        finally:
            return feature_list

    def get_hostmodel_name(self):
        """
        Get CPU modelname which explicitly specified by <model>.text
        in cpu/mode[@name='host-model'] part of virsh domcapabilities.

        In libvirt 3.9 and above, domcapabilities give the overall features supported
        by current host/qemu/kvm via CPU model and a bunch of additional features. CPU
        model is one set of features defined by libvirt in '/usr/share/libvirt/cpu_map.xml'
        Specific features described in domcapabilities are additional features, the valid
        policy values are 'require' and 'disable', 'require' means the feature can be emulated
        by host/qemu/kvm, 'disable' which means feature is disabled by current system due to
        host CPU doesn't support or qemu/kvm has no ability to emulate it or some other
        reasons like the feature block migration and so on.

        Below is one snipped CPU host-model part output of domcapabilities.
        <feature> tag specify additional feature policy for one certain feature type.

        virsh domcapabilities  | xmllint -xpath "/domainCapabilities/cpu/mode[@name='host-model']" -
        <mode name="host-model" supported="yes">
            <model fallback="forbid">Skylake-Client</model>
            <vendor>Intel</vendor>
            <feature policy="require" name="ss"/>
            <feature policy="require" name="hypervisor"/>
            <feature policy="require" name="tsc_adjust"/>
            <feature policy="require" name="clflushopt"/>
            <feature policy="require" name="pdpe1gb"/>
            <feature policy="require" name="invtsc"/>
        </mode>
        Below is one snipped CPU host-model part output of domcapabilities.
        feature tag specific policy for one specific feature type.

        virsh domcapabilities  | xmllint -xpath "/domainCapabilities/cpu/mode[@name='host-model']" -
        <mode name="host-model" supported="yes">
            <model fallback="forbid">Skylake-Client</model>
            <vendor>Intel</vendor>
            <feature policy="require" name="ss"/>
        </mode>

        :return: modelname string
        """
        xmltreefile = self.__dict_get__("xml")
        try:
            for mode_node in xmltreefile.findall("/cpu/mode"):
                if mode_node.get("name") == "host-model":
                    return mode_node.find("model").text
        except AttributeError as elem_attr:
            LOG.warning("Failed to find attribute %s" % elem_attr)
            return ""


class DomCapFeaturesXML(base.LibvirtXMLBase):
    """
    Handler of feature element in libvirt domcapabilities.

    Properties:
        gic_supported:
            string in "yes" or "no"
        gic_enums:
            list of enum dict in /gic
        hyperv_supported:
            string in "yes" or "no"
        hyperv_enums:
            list of enum dict in /hyperv
    """

    __slots__ = ("gic_supported", "gic_enums", "hyperv_supported", "hyperv_enums")

    def __init__(self, virsh_instance=base.virsh):
        accessors.XMLAttribute(
            property_name="gic_supported",
            libvirtxml=self,
            parent_xpath="/",
            tag_name="gic",
            attribute="supported",
        )
        accessors.XMLAttribute(
            property_name="hyperv_supported",
            libvirtxml=self,
            parent_xpath="/",
            tag_name="hyperv",
            attribute="supported",
        )
        accessors.AllForbidden(property_name="gic_enums", libvirtxml=self)
        accessors.AllForbidden(property_name="hyperv_enums", libvirtxml=self)
        super(DomCapFeaturesXML, self).__init__(virsh_instance)

    def get_gic_enums(self):
        """
        Return EnumXML instance list of gic
        """
        return self.get_enums("/gic/enum")

    def get_hyperv_enums(self):
        """
        Return EnumXML instance list of hyperv
        """
        return self.get_enums("/hyperv/enum")

    def get_enums(self, path):
        """
        Return EnumXML instance list of specified element

        :param path: str, like '/gic/enum', '/hyperv/enum'
        """
        enum_list = []
        for enum_node in self.xmltreefile.findall(path):
            xml_str = xml_utils.ElementTree.tostring(enum_node, encoding="unicode")
            new_enum = EnumXML()
            new_enum.xml = xml_str
            enum_list.append(new_enum)
        return enum_list


class ValueXML(base.LibvirtXMLBase):
    """
    Value elements of EnumXML
    """

    __slots__ = ("value",)

    def __init__(self, virsh_instance=base.virsh):
        accessors.XMLElementText(
            property_name="value", libvirtxml=self, parent_xpath="/", tag_name="value"
        )
        super(ValueXML, self).__init__(virsh_instance=virsh_instance)
        self.xml = "<value/>"


class EnumXML(base.LibvirtXMLBase):
    """
    Handler of Enum element in libvirt domcapabilities

    Properties:
        name:
            string of name for enum
        values:
            list of ValueXML instance
    """

    __slots__ = ("name", "values")

    def __init__(self, virsh_instance=base.virsh):
        accessors.XMLAttribute(
            property_name="name",
            libvirtxml=self,
            parent_xpath="/",
            tag_name="enum",
            attribute="name",
        )
        accessors.XMLElementList(
            property_name="values",
            libvirtxml=self,
            parent_xpath="/",
            marshal_from=self.marshal_from_values,
            marshal_to=self.marshal_to_values,
            has_subclass=True,
        )
        super(EnumXML, self).__init__(virsh_instance=virsh_instance)
        self.xml = "<enum/>"

    @staticmethod
    def marshal_from_values(item, index, libvirtxml):
        """
        Convert an ValueXML object to value tag and xml element.
        """
        if isinstance(item, ValueXML):
            return "value", item
        elif isinstance(item, str):
            value = ValueXML()
            value.value = item
            return "value", value
        else:
            raise xcepts.LibvirtXMLError(
                "Expected a list of ValueXML " "instances, not a %s" % str(item)
            )

    @staticmethod
    def marshal_to_values(tag, new_treefile, index, libvirtxml):
        """
        Convert a value tag xml element to an object of ValueXML.
        """
        if tag != "value":
            return None  # Don't convert this item
        newone = ValueXML(virsh_instance=libvirtxml.virsh)
        newone.xmltreefile = new_treefile
        return newone
