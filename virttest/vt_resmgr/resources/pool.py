import uuid
from abc import ABC, abstractmethod
from copy import deepcopy

from virttest.vt_cluster import cluster


class _ResourcePool(ABC):
    """
    A resource pool is used to manage resources. A resource must be
    allocated from a specific pool, and a pool can hold many resources
    """
    _POOL_TYPE = None

    def __init__(self, pool_config):
        self._config = pool_config
        self.pool_meta["uuid"] = uuid.uuid4().hex
        self._resources = dict()  # {resource id: resource object}
        self._caps = dict()

        if not set(self.attaching_nodes).difference(set(["*"])):
            self.attaching_nodes = [n.name for n in cluster.get_all_nodes()]

    @property
    def pool_name(self):
        return self.pool_meta["name"]

    @property
    def pool_id(self):
        return self.pool_meta["uuid"]

    @property
    def pool_config(self):
        return self._config

    def customize_pool_config(self, node_name):
        return self.pool_config

    @property
    def pool_meta(self):
        return self._config["meta"]

    @property
    def pool_spec(self):
        return self._config["spec"]

    @property
    def resources(self):
        return self._resources

    def get_info(self, verbose=False):
        return deepcopy(self.pool_config)

    @classmethod
    def define_config(cls, pool_name, pool_params):
        access = pool_params.get("access", {})
        return {
            "meta": {
                "name": pool_name,
                "uuid": None,
                "type": pool_params["type"],
                "access": access,
            },
            "spec": {},
        }

    @abstractmethod
    def meet_resource_request(self, resource_type, resource_params):
        """
        Check if the pool can support a resource's allocation
        """
        raise NotImplementedError

    def define_resource_config(self, resource_name, resource_type, resource_params):
        """
        Define the resource configuration, format:
          {"meta": {...}, "spec": {...}}
        It depends on the specific resource.

        Note that we cannot set binding nodes here, as only the resource itself
        can determine its binding nodes based on the Cartesian parameters.
        Alternatively, the higher-level function callers are responsible for
        knowing which nodes should be bound.
        """
        res_cls = self.get_resource_class(resource_type)
        config = res_cls.define_config(resource_name, resource_params)

        config["meta"].update(
            {
                "pool": self.pool_id,
            }
        )

        return config

    @classmethod
    @abstractmethod
    def get_resource_class(cls, resource_type):
        raise NotImplementedError

    def create_object(self):
        pass

    def destroy_object(self):
        pass

    def create_resource_object_from(self, resource):
        # Check if the pool can support a specific type of resource
        resource_class = self.get_resource_class(resource.resource_type)
        if resource_class is None:
            raise RuntimeError(f"The {resource.resource_type} type resource is not supported by pool {self.pool_id}")

        new_resource_config = resource.define_config_from_self(self.pool_id)
        return self.create_resource_object(new_resource_config)

    def create_resource_object(self, resource_config):
        """
        Create a resource object, no real resource allocated
        """
        meta = resource_config["meta"]
        res_cls = self.get_resource_class(meta["type"])
        res = res_cls(resource_config)
        res.create_object()
        self.resources[res.resource_id] = res
        return res.resource_id

    def destroy_resource_object(self, resource_id):
        """
        Destroy the resource object, all its backings should be released
        """
        resource = self.resources.pop(resource_id)
        resource.destroy_object()

    def clone_resource(self, resource_id):
        resource = self.resources.get(resource_id)
        cloned_resource_id = self.create_resource_object_from(resource)
        cloned_resource = self.resources[cloned_resource_id]

        # Set the same bindings as the source resource
        cloned_resource.resource_meta.update({
            "bindings": resource.resource_bindings.copy(),
        })

        cloned_resource.bind(dict())
        cloned_resource.allocate(dict())

        return clone.resource_id

    def update_resource(self, resource_id, config):
        resource = self.resources.get(resource_id)
        cmd, arguments = config.popitem()

        # nodes should be the node names defined in cluster.json
        node_names = arguments.get("nodes")
        if node_names:
            # Check if the node can access the resource pool
            if not set(node_names).issubset(set(self.attaching_nodes)):
                raise ValueError(
                    f"Not all nodes({node_names}) can access the pool {self.pool_id}"
                )

        handler = resource.get_update_handler(cmd)
        return handler(arguments)

    def get_resource_info(self, resource_id, verbose=False):
        """
        Get the reference of a specified resource
        """
        resource = self.resources.get(resource_id)
        config = deepcopy(resource.resource_config)
        if verbose:
            config["meta"]["pool"] = deepcopy(self.pool_config)

        return config

    @property
    def attaching_nodes(self):
        return self.pool_meta["access"].get("nodes")

    @attaching_nodes.setter
    def attaching_nodes(self, nodes):
        self.pool_meta["access"]["nodes"] = nodes

    """
    @property
    def pool_capability(self):
        node_name = self.attaching_nodes[0]
        node = cluster.get_node(node_name)
        r, o = node.proxy.resource.get_pool_capability()
        if r != 0:
            raise Exception(o["out"])
    """

    @classmethod
    def get_pool_type(cls):
        return cls._POOL_TYPE
