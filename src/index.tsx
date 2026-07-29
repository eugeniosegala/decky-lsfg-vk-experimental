import { staticClasses } from "@decky/ui";
import { definePlugin } from "@decky/api";
import { GiPlasticDuck } from "react-icons/gi";
import { Content } from "./components/Content";

export default definePlugin(() => {
  console.log("decky-lsfg-vk-experimental plugin initializing");

  return {
    name: "Decky LSFG-VK Experimental",
    titleView: <div className={staticClasses.Title}>Decky LSFG-VK Experimental</div>,
    alwaysRender: true,
    content: <Content />,
    icon: <GiPlasticDuck />,
    onDismount() {
      console.log("decky-lsfg-vk-experimental unloading");
    }
  };
});
